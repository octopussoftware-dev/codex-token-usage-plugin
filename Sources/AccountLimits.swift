import Foundation
import CoreFoundation
import Darwin

// A separate, read-only account request. No threads or turns are started.
final class AccountLimits {
    private var last:JSON?
    private var lastFailure:String?
    private var nextRead:Double = 0

    func read(refresh:Bool = false) -> JSON {
        let now=Date().timeIntervalSince1970
        if refresh || now>=nextRead {
            do {
                let response=try LimitsConnection().read()
                last=Self.normalize(response,at:Date().timeIntervalSince1970)
                lastFailure=nil
            } catch let error as LimitsError { lastFailure=error.message }
            catch { lastFailure="Could not refresh account allowance. Check your Codex sign-in and connection." }
            nextRead=Date().timeIntervalSince1970+60
        }
        var value=last ?? ["status":"unavailable","windows":[],"observedAt":NSNull(),"message":"Account allowance is unavailable."]
        value["source"]="codex-app-server"
        value["scope"]="account"
        if let failure=lastFailure {
            value["status"]=last == nil ? "unavailable" : "stale"
            value["message"]=failure
        }
        return value
    }

    static func finite(_ value:Any?) -> Double? {
        guard let n=value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.isFinite else { return nil }
        return n.doubleValue
    }

    static func normalize(_ response:JSON,at time:Double) -> JSON {
        let multiple=response["rateLimitsByLimitId"] as? [String:JSON]
        let buckets:[String:JSON]
        if let multiple, !multiple.isEmpty { buckets=multiple }
        else if let legacy=response["rateLimits"] as? JSON { buckets=[str(legacy["limitId"]) ?? "codex":legacy] }
        else { buckets=[:] }
        var windows:[JSON]=[]
        for key in buckets.keys.sorted(by: { a,b in a=="codex" ? b != "codex" : b=="codex" ? false : a<b }) {
            let bucket=buckets[key]!
            for slot in ["primary","secondary"] {
                guard let window=bucket[slot] as? JSON else { continue }
                let used=finite(window["usedPercent"]).map { min(100,max(0,$0)) }
                let duration=finite(window["windowDurationMins"]).flatMap { $0>0 ? $0 : nil }
                let reset=finite(window["resetsAt"]).flatMap { $0>0 && $0<253402300800 ? $0 : nil }
                windows.append(["id":key+":"+slot,"limitId":key,"limitName":short(str(bucket["limitName"]) ?? (key=="codex" ? "Codex" : key),limit:80),"usedPercent":used as Any? ?? NSNull(),"remainingPercent":used.map { 100-$0 } as Any? ?? NSNull(),"windowDurationMins":duration as Any? ?? NSNull(),"resetsAt":reset as Any? ?? NSNull()])
            }
        }
        let available=windows.contains { $0["remainingPercent"] is Double }
        return ["status":available ? "available" : "unavailable","windows":windows,"observedAt":time,"message":available ? "" : "Remaining allowance is not reported for this Codex sign-in."]
    }
}

private struct LimitsError:Error {
    let message:String
    static let unavailable=LimitsError(message:"Could not refresh account allowance. Check your Codex sign-in and connection.")
    static let timeout=LimitsError(message:"Account allowance did not respond. Try Refresh.")
}

private final class LimitsConnection {
    private let process=Process(), input=Pipe(), output=Pipe(), exited=DispatchSemaphore(value:0)
    private var buffer=Data()
    private let deadline=Date().addingTimeInterval(15)

    private func executable() throws -> URL {
        let env=ProcessInfo.processInfo.environment, files=FileManager.default
        if let override=env["COST_CALCULATOR_CODEX_BIN"] {
            guard override.hasPrefix("/"), files.isExecutableFile(atPath:override) else { throw LimitsError(message:"The configured Codex executable is unavailable.") }
            return URL(fileURLWithPath:override)
        }
        let paths=(env["PATH"] ?? "").split(separator:":").filter { $0.hasPrefix("/") }.map { String($0)+"/codex" }
        let candidates=paths+["/Applications/Codex.app/Contents/Resources/codex","/Applications/ChatGPT.app/Contents/Resources/codex","/opt/homebrew/bin/codex","/usr/local/bin/codex"]
        guard let path=candidates.first(where:{ files.isExecutableFile(atPath:$0) }) else { throw LimitsError(message:"Codex could not be found. Install the Codex CLI to read account allowance.") }
        return URL(fileURLWithPath:path)
    }

    func read() throws -> JSON {
        process.executableURL=try executable()
        process.arguments=["app-server","--listen","stdio://"]
        process.currentDirectoryURL=FileManager.default.homeDirectoryForCurrentUser
        process.standardInput=input; process.standardOutput=output; process.standardError=FileHandle.nullDevice
        process.terminationHandler={ [exited] _ in exited.signal() }
        try process.run()
        input.fileHandleForReading.closeFile(); output.fileHandleForWriting.closeFile()
        defer {
            input.fileHandleForWriting.closeFile()
            if exited.wait(timeout:.now()+0.3) == .timedOut {
                if process.isRunning { process.terminate() }
                if exited.wait(timeout:.now()+0.3) == .timedOut, process.isRunning {
                    Darwin.kill(process.processIdentifier,SIGKILL)
                    _=exited.wait(timeout:.now()+1)
                }
            }
            output.fileHandleForReading.closeFile()
        }
        _=try request(1,"initialize",["clientInfo":["name":"token_usage","title":"Token Usage","version":PluginServer.version]])
        try send(["method":"initialized"])
        return try request(2,"account/rateLimits/read",nil)
    }

    private func send(_ message:JSON) throws {
        try input.fileHandleForWriting.write(contentsOf:JSONSerialization.data(withJSONObject:message)+Data([10]))
    }

    private func request(_ id:Int,_ method:String,_ params:JSON?) throws -> JSON {
        var message:JSON=["id":id,"method":method]
        if let params { message["params"]=params }
        try send(message)
        while Date()<deadline {
            while let newline=buffer.firstIndex(of:10) {
                let line=buffer.prefix(upTo:newline); buffer.removeSubrange(...newline)
                guard let message=(try? JSONSerialization.jsonObject(with:line)) as? JSON else { continue }
                // Never service server-initiated actions or expose raw errors/auth details.
                if message["method"] != nil {
                    if let requestID=message["id"] { try send(["id":requestID,"error":["code":-32601,"message":"Read-only client"]]) }
                    continue
                }
                guard (message["id"] as? NSNumber)?.intValue==id else { continue }
                guard message["error"]==nil, let result=message["result"] as? JSON else { throw LimitsError.unavailable }
                return result
            }
            let remaining=deadline.timeIntervalSinceNow
            guard remaining>0 else { throw LimitsError.timeout }
            var descriptor=pollfd(fd:output.fileHandleForReading.fileDescriptor,events:Int16(POLLIN),revents:0)
            let ready=Darwin.poll(&descriptor,1,Int32(min(remaining*1000,15000)))
            if ready<0 && errno==EINTR { continue }
            guard ready>0 else { throw ready==0 ? LimitsError.timeout : LimitsError.unavailable }
            var bytes=[UInt8](repeating:0,count:16384)
            let count=Darwin.read(descriptor.fd,&bytes,bytes.count)
            if count<0 && errno==EINTR { continue }
            guard count>0 else { throw LimitsError.unavailable }
            buffer.append(contentsOf:bytes.prefix(count))
            guard buffer.count<=1048576 else { throw LimitsError.unavailable }
        }
        throw LimitsError.timeout
    }
}
