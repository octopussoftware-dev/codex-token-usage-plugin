import Foundation
import SQLite3

func dict(_ value: Any?) -> JSON { value as? JSON ?? [:] }
func str(_ value: Any?) -> String? { guard let v = value as? String, !v.isEmpty else { return nil }; return v }
func number(_ value: Any?) -> Int64 { max(0, (value as? NSNumber)?.int64Value ?? 0) }
func short(_ value: String, limit: Int = 240) -> String { String(value.split(whereSeparator: { $0.isWhitespace }).joined(separator:" ").prefix(limit)) }
func excerpt(_ value:String) -> String {
    let plain=value.replacingOccurrences(of:"\\[([^\\]]+)\\]\\([^)]*\\)",with:"$1",options:.regularExpression)
        .replacingOccurrences(of:"https?://\\S+",with:"",options:.regularExpression)
        .replacingOccurrences(of:"**",with:"").replacingOccurrences(of:"`",with:"")
        .split(whereSeparator:{ $0.isWhitespace }).joined(separator:" ")
    return plain.count>220 ? String(plain.prefix(220))+"…" : plain
}
let dateParser: ISO8601DateFormatter = { let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime,.withFractionalSeconds]; return f }()
func stamp(_ text: String?) -> Double { guard let text else { return 0 }; return dateParser.date(from:text)?.timeIntervalSince1970 ?? ISO8601DateFormatter().date(from:text)?.timeIntervalSince1970 ?? 0 }

struct Usage {
    var input: Int64 = 0, cached: Int64 = 0, writes: Int64 = 0, output: Int64 = 0, reasoning: Int64 = 0
    init(_ value: JSON = [:]) { input=number(value["input_tokens"]); cached=min(input,number(value["cached_input_tokens"])); writes=min(input-cached,number(value["cache_write_input_tokens"])); output=number(value["output_tokens"]); reasoning=min(output,number(value["reasoning_output_tokens"])) }
    var total: Int64 { input+output }
    mutating func add(_ other: Usage) { input+=other.input; cached+=other.cached; writes+=other.writes; output+=other.output; reasoning+=other.reasoning }
    var json: JSON { ["input":input,"cached":cached,"cacheWrite":writes,"output":output,"reasoning":reasoning,"total":total] }
}
enum UsageRange:String, CaseIterable {
    case all, day, week, month
    var seconds:Double? { switch self { case .all:return nil; case .day:return 86400; case .week:return 7*86400; case .month:return 30*86400 } }
    var label:String { switch self { case .all:return "All recorded time"; case .day:return "Last 24 hours"; case .week:return "Last 7 days"; case .month:return "Last 30 days" } }
}
struct UsageWindow {
    let range:UsageRange, end:Double
    var exclusiveEnd=false
    var start:Double? { range.seconds.map { end-$0 } }
    var previous:UsageWindow? { start.map { UsageWindow(range:range,end:$0,exclusiveEnd:true) } }
    func contains(_ timestamp:Double)->Bool { guard let start else { return true }; return timestamp>=start && (exclusiveEnd ? timestamp<end : timestamp<=end) }
    var json:JSON { ["id":range.rawValue,"label":exclusiveEnd ? range.label.replacingOccurrences(of:"Last ",with:"Previous ") : range.label,"start":start as Any? ?? NSNull(),"end":end,"endExclusive":exclusiveEnd] }
}
struct ResponseUsage { var turn:String, model:String, usage:Usage, timestamp:Double }
struct ChatRecord {
    var id:String, path:String, title:String, project:String, projectKey:String, model:String, effort:String, parent:String?, subagent:Bool, nickname:String, created:Double, updated:Double, recordedTokens:Int64
}
final class Rollout {
    var offset=0, modified:Double=0, fileID:UInt64=0, sourceSize=0, sourceCompressed=false, failed=false, malformed=false
    var model="", effort="", turn="", parent:String?, forked=false
    var activity="No activity recorded", activityAt:Double=0, status="No activity", commentary=""
    var canonical:[String:ResponseUsage]=[:], fallback:[ResponseUsage]=[], lastTotals:[String:String]=[:]
    var seenUsage=false, legacyInheritedSkipped=false
    func parse(_ record:ChatRecord, home:URL) {
        failed=false
        let original=URL(fileURLWithPath:record.path).resolvingSymlinksInPath()
        let compressed = !FileManager.default.fileExists(atPath:original.path)
        let url = (compressed ? original.appendingPathExtension("zst") : original).resolvingSymlinksInPath()
        let allowed=["sessions","archived_sessions"].map { home.appendingPathComponent($0).resolvingSymlinksInPath().path+"/" }
        guard original.pathExtension == "jsonl", allowed.contains(where: { url.path.hasPrefix($0) }), let attrs=try? FileManager.default.attributesOfItem(atPath:url.path), let size=(attrs[.size] as? NSNumber)?.intValue else { failed=true; return }
        let mtime=(attrs[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0, inode=(attrs[.systemFileNumber] as? NSNumber)?.uint64Value ?? 0
        if fileID==inode && modified==mtime && sourceSize==size && sourceCompressed==compressed { return }
        if compressed || sourceCompressed != compressed || offset>size || (fileID != 0 && fileID != inode) || (offset==size && modified != 0 && modified != mtime) { reset() }
        guard let encoded=try? Data(contentsOf:url,options:.mappedIfSafe) else { failed=true; return }
        let data:Data
        if compressed {
            var count=0
            let bytes=encoded.withUnsafeBytes { raw in cost_zstd_decode(raw.bindMemory(to:UInt8.self).baseAddress,raw.count,&count) }
            guard let bytes else { failed=true; return }
            data=Data(bytesNoCopy:bytes,count:count,deallocator:.free)
        } else { data=encoded }
        fileID=inode; modified=mtime; sourceSize=size; sourceCompressed=compressed
        data.withUnsafeBytes { raw in
            guard let base=raw.baseAddress else { return }
            var position=offset
            while position<raw.count, let end=memchr(base.advanced(by:position),10,raw.count-position) {
                let length=base.advanced(by:position).distance(to:UnsafeRawPointer(end))
                let prefix=String(decoding:UnsafeRawBufferPointer(start:base.advanced(by:position),count:min(length,480)),as:UTF8.self)
                if prefix.contains("token_usage_record") || prefix.contains("turn_context") || prefix.contains("session_meta") || prefix.contains("event_msg") || (prefix.contains("response_item") && (prefix.contains("\"message\"") || prefix.contains("\"function_call\"") || prefix.contains("\"custom_tool_call\""))) {
                    let line=Data(bytes:base.advanced(by:position),count:length)
                    if let value=(try? JSONSerialization.jsonObject(with:line)) as? JSON { consume(value,record:record) }
                    else { malformed=true }
                }
                position+=length+1; offset=position
            }
        }
    }
    func reset() { offset=0; model=""; effort=""; turn=""; parent=nil; forked=false; canonical=[:]; fallback=[]; lastTotals=[:]; activity="No activity recorded"; activityAt=0; status="No activity"; commentary=""; seenUsage=false; malformed=false; legacyInheritedSkipped=false }
    func consume(_ event:JSON,record:ChatRecord) {
        let type=str(event["type"]) ?? "", p=dict(event["payload"]), time=stamp(str(event["timestamp"]))
        if type=="session_meta" {
            parent=str(p["parent_thread_id"]); forked=str(p["forked_from_id"]) != nil
            return
        }
        if type=="turn_context" {
            turn=str(p["turn_id"]) ?? turn; model=str(p["model"]) ?? ""; effort=str(p["effort"]) ?? str(p["reasoning_effort"]) ?? ""
            return
        }
        // Forked legacy logs may contain copied context. Never count those inherited responses twice.
        if forked && time>0 && time<record.created-1 { return }
        if type=="token_usage_record" {
            guard str(p["thread_id"]) == record.id else { return }
            seenUsage=true
            let key=str(p["response_id"]) ?? "offset-\(offset)"
            // Repeated accounting updates belong to the original response time.
            let recordedAt=canonical[key].map { $0.timestamp>0 ? $0.timestamp : time } ?? time
            canonical[key]=ResponseUsage(turn:str(p["turn_id"]) ?? turn,model:str(p["model"]) ?? model,usage:Usage(dict(p["usage"])),timestamp:recordedAt)
        } else if type=="event_msg" {
            let kind=str(p["type"]) ?? ""
            if kind=="token_count", let info=p["info"] as? JSON {
                let total=dict(info["total_token_usage"])
                let signature=["input_tokens","cached_input_tokens","cache_write_input_tokens","output_tokens","reasoning_output_tokens"].map { String(number(total[$0])) }.joined(separator:":")
                if lastTotals["thread"] != signature {
                    lastTotals["thread"]=signature
                    if let last=info["last_token_usage"] as? JSON { fallback.append(ResponseUsage(turn:turn,model:model,usage:Usage(last),timestamp:time)); seenUsage=true }
                    else { legacyInheritedSkipped=true }
                }
            } else if kind=="task_started" {
                turn=str(p["turn_id"]) ?? turn; status="Working"; activity="Starting a turn"; commentary=""; activityAt=time
            } else if kind=="task_complete" || kind=="turn_complete" {
                status="Finished"; activity="Turn complete"; activityAt=time
                if let message=str(p["last_agent_message"]) { commentary=excerpt(message) }
            } else if kind=="turn_aborted" { status="Interrupted"; activity="Turn interrupted"; activityAt=time }
            else if kind=="agent_message", let message=str(p["message"]) { commentary=excerpt(message); activityAt=time }
            else if kind=="item_completed" { updateActivity(dict(p["item"]),time:time) }
        } else if type=="response_item" { updateActivity(p,time:time) }
    }
    func updateActivity(_ item:JSON,time:Double) {
        let type=str(item["type"]) ?? ""
        if type=="message" || type=="agentMessage" {
            guard str(item["role"]) == "assistant" || type=="agentMessage" else { return }
            if str(item["channel"]) == "analysis" { return }
            let content=(item["content"] as? [JSON] ?? []).compactMap { str($0["text"]) }.joined(separator:" ")
            let message=str(item["text"]) ?? content
            if !message.isEmpty { commentary=excerpt(message); activityAt=time; activity = str(item["phase"]) == "final_answer" ? "Responding" : "Updating progress" }
        } else if type=="function_call" || type=="custom_tool_call" {
            let name=str(item["name"]) ?? "tool"
            if name.contains("request_user_input") { activity="Waiting for input"; status="Waiting" }
            else if name.contains("exec") || name.contains("shell") { activity="Running a command" }
            else if name.contains("apply_patch") { activity="Editing files" }
            else if name.contains("search") || name.contains("web") { activity="Researching" }
            else if name.contains("spawn_agent") { activity="Delegating work" }
            else if name.contains("wait") { activity="Waiting for results" }
            else { activity="Using "+short(name,limit:60) }
            activityAt=time
        }
    }
    var responses:[ResponseUsage] {
        let turns=Set(canonical.values.map { $0.turn })
        return Array(canonical.values)+fallback.filter { !turns.contains($0.turn) }
    }
}
struct UsageTotal {
    var tokens=Usage(), missing=0
    mutating func add(_ other:UsageTotal) { tokens.add(other.tokens); missing+=other.missing }
    var json:JSON { ["tokens":tokens.json,"missingAgents":missing,"complete":missing==0] }
}
final class CostStore {
    let home:URL
    var logs:[String:Rollout]=[:]
    init() { home=URL(fileURLWithPath:ProcessInfo.processInfo.environment["CODEX_HOME"] ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex").path).resolvingSymlinksInPath() }
    func catalog() throws -> [String:ChatRecord] {
        guard let files=try? FileManager.default.contentsOfDirectory(at:home,includingPropertiesForKeys:nil), let path=files.filter({ $0.lastPathComponent.hasPrefix("state_") && $0.pathExtension=="sqlite" }).sorted(by: { $0.lastPathComponent.compare($1.lastPathComponent,options:.numeric) == .orderedDescending }).first else { return [:] }
        var db:OpaquePointer?
        guard sqlite3_open_v2(path.path,&db,SQLITE_OPEN_READONLY|SQLITE_OPEN_NOMUTEX,nil)==SQLITE_OK else { if db != nil { sqlite3_close(db) }; throw problem("Could not read the local session catalog.") }
        defer { sqlite3_close(db) }; sqlite3_busy_timeout(db,500)
        var columns=Set<String>(), stmt:OpaquePointer?
        sqlite3_prepare_v2(db,"PRAGMA table_info(threads)",-1,&stmt,nil)
        while sqlite3_step(stmt)==SQLITE_ROW { if let c=sqlite3_column_text(stmt,1) { columns.insert(String(cString:c)) } }; sqlite3_finalize(stmt)
        func col(_ name:String,_ fallback:String="NULL") -> String { columns.contains(name) ? name : fallback }
        let query="SELECT id,rollout_path,COALESCE(NULLIF(\(col("name")),''),title),cwd,\(col("model")),\(col("reasoning_effort")),source,\(col("thread_source")),\(col("agent_nickname")),created_at,updated_at,\(col("tokens_used","0")) FROM threads ORDER BY updated_at DESC"
        guard sqlite3_prepare_v2(db,query,-1,&stmt,nil)==SQLITE_OK else { throw problem("This local session catalog format is not supported.") }
        var rows:[String:ChatRecord]=[:]
        func text(_ n:Int32)->String { sqlite3_column_text(stmt,n).map { String(cString:$0) } ?? "" }
        while sqlite3_step(stmt)==SQLITE_ROW {
            let source=text(6), kind=text(7), model=text(4)
            if kind=="guardian_review" || kind=="voice_chat" || model=="codex-auto-review" { continue }
            let sourceData=source.data(using:.utf8).flatMap { try? JSONSerialization.jsonObject(with:$0) }
            let spawn=dict(dict(dict(sourceData)["subagent"])["thread_spawn"])
            let id=text(0), cwd=text(3)
            let projectKey=cwd.isEmpty ? "" : URL(fileURLWithPath:cwd).standardizedFileURL.path
            let project=projectKey.isEmpty ? "Other chats" : URL(fileURLWithPath:projectKey).lastPathComponent
            rows[id]=ChatRecord(id:id,path:text(1),title:short(text(2).isEmpty ? "Untitled chat" : text(2),limit:200),project:project,projectKey:projectKey,model:model,effort:text(5),parent:str(spawn["parent_thread_id"]),subagent:kind=="subagent" || source.contains("subagent"),nickname:text(8),created:sqlite3_column_double(stmt,9),updated:sqlite3_column_double(stmt,10),recordedTokens:sqlite3_column_int64(stmt,11))
        }
        sqlite3_finalize(stmt); stmt=nil
        if sqlite3_prepare_v2(db,"SELECT parent_thread_id,child_thread_id FROM thread_spawn_edges",-1,&stmt,nil)==SQLITE_OK {
            while sqlite3_step(stmt)==SQLITE_ROW { let parent=text(0),child=text(1); if rows[child] != nil { rows[child]?.parent=parent; rows[child]?.subagent=true } }
        }
        sqlite3_finalize(stmt)
        return rows
    }
    func problem(_ message:String)->NSError { NSError(domain:"CostCalculator",code:1,userInfo:[NSLocalizedDescriptionKey:message]) }
    func agent(_ record:ChatRecord,depth:Int,window:UsageWindow) -> (JSON,UsageTotal,UsageTotal) {
        let log=logs[record.id] ?? Rollout(); logs[record.id]=log; log.parse(record,home:home)
        let previousWindow=window.previous
        var total=UsageTotal(), previous=UsageTotal(), byModel:[String:UsageTotal]=[:], undated=false
        for response in log.responses {
            if window.start != nil && response.timestamp<=0 && response.usage.total>0 { undated=true }
            if previousWindow?.contains(response.timestamp)==true { previous.tokens.add(response.usage) }
            guard window.contains(response.timestamp) else { continue }
            let model=response.model.isEmpty ? "Unknown model" : response.model
            var subtotal=byModel[model] ?? UsageTotal(); subtotal.tokens.add(response.usage)
            byModel[model]=subtotal
        }
        for subtotal in byModel.values { total.add(subtotal) }
        if undated || log.failed || log.malformed || log.legacyInheritedSkipped || (!log.seenUsage && record.recordedTokens>0) {
            total.missing=1
            if previousWindow != nil { previous.missing=1 }
        }
        let status = log.status=="Working" && Date().timeIntervalSince1970-log.activityAt>300 ? "Status unknown" : log.status
        var value:JSON=["id":record.id,"parentId":record.parent as Any? ?? NSNull(),"title":record.title,"name":depth==0 ? "Main agent" : record.nickname.isEmpty ? record.title : record.nickname,"depth":depth,"model":log.model.isEmpty ? record.model.isEmpty ? "Unknown" : record.model : log.model,"effort":log.effort.isEmpty ? record.effort.isEmpty ? "Unspecified" : record.effort : log.effort,"status":status,"activity":log.activity,"activityAt":log.activityAt,"summary":log.commentary,"usage":total.json,"usageSource":log.canonical.isEmpty ? "Legacy response usage" : "Per-response usage","models":byModel.keys.sorted().map { ["model":$0,"usage":byModel[$0]!.json] as JSON }]
        value["previousUsage"]=previousWindow == nil ? NSNull() : previous.json
        if log.failed { value["note"]="Usage log unavailable. This agent’s tokens are missing from the total." }
        else if undated { value["note"]="Some usage timestamps are missing. Undated tokens are excluded from this period." }
        else if total.missing>0 { value["note"]="Some usage records are missing or incomplete." }
        else if log.forked { value["note"]="Only this chat’s own responses are counted; inherited history is excluded." }
        return (value,total,previous)
    }
    func sourceUpdatedAt(_ record:ChatRecord)->Double {
        let original=URL(fileURLWithPath:record.path).resolvingSymlinksInPath()
        guard ["sessions","archived_sessions"].contains(where:{ original.path.hasPrefix(home.appendingPathComponent($0).path+"/") }) else { return record.updated }
        let url=FileManager.default.fileExists(atPath:original.path) ? original : original.appendingPathExtension("zst")
        let modified=(try? FileManager.default.attributesOfItem(atPath:url.path)[.modificationDate]) as? Date
        return max(record.updated,modified?.timeIntervalSince1970 ?? 0)
    }
    func snapshot(query:String="",limit:Int=20,thread:String?=nil,range:UsageRange = .all) throws -> JSON {
        let window=UsageWindow(range:range,end:Date().timeIntervalSince1970)
        let records=try catalog()
        var children:[String:[ChatRecord]]=[:]
        for record in records.values { if let parent=record.parent { children[parent,default:[]].append(record) } }
        let roots=records.values.filter { !$0.subagent && $0.parent==nil }.sorted { $0.updated==$1.updated ? $0.id<$1.id : $0.updated>$1.updated }
        var matches=roots.filter { query.isEmpty || ($0.title+" "+$0.project).localizedCaseInsensitiveContains(query) }
        if let since=window.previous?.start, thread==nil {
            // Metadata is only a scan prefilter. Token timestamps decide the totals.
            // Include descendant activity so an older parent with a recent child is found.
            let recent=Dictionary(uniqueKeysWithValues:records.values.map { ($0.id,sourceUpdatedAt($0)) })
            func newest(_ root:ChatRecord)->Double {
                var pending=[root],visited=Set<String>(),updated=0.0
                while let record=pending.popLast() {
                    guard visited.insert(record.id).inserted else { continue }
                    updated=max(updated,recent[record.id] ?? record.updated)
                    pending.append(contentsOf:children[record.id] ?? [])
                }
                return updated
            }
            var recentRoots:[(record:ChatRecord,updated:Double)]=[]
            for root in matches {
                let updated=newest(root)
                if updated>=since { recentRoots.append((root,updated)) }
            }
            recentRoots.sort { lhs,rhs in lhs.updated==rhs.updated ? lhs.record.id<rhs.record.id : lhs.updated>rhs.updated }
            matches=recentRoots.map { $0.record }
        }
        let chosen:[ChatRecord]
        if let thread { guard let root=roots.first(where: { $0.id==thread }) else { throw problem("This parent chat is no longer available.") }; chosen=[root] }
        else { chosen=window.start==nil ? Array(matches.prefix(limit)) : matches }
        var groups:[JSON]=[], grand=UsageTotal(), previousGrand=UsageTotal(), matchingCount=0
        for root in chosen {
            var agents:[JSON]=[], total=UsageTotal(), previous=UsageTotal(), visited=Set<String>()
            func walk(_ record:ChatRecord,_ depth:Int) {
                guard visited.insert(record.id).inserted else { return }
                let (value,usage,previousUsage)=agent(record,depth:depth,window:window); agents.append(value); total.add(usage); previous.add(previousUsage)
                for child in (children[record.id] ?? []).sorted(by: { $0.created<$1.created }) { walk(child,depth+1) }
            }
            walk(root,0)
            if thread==nil && window.start != nil && total.tokens.total==0 && previous.tokens.total==0 && total.missing==0 && previous.missing==0 { continue }
            matchingCount+=1
            guard groups.count<limit || thread != nil else { continue }
            grand.add(total); previousGrand.add(previous)
            let latest=agents.max { ( $0["activityAt"] as? Double ?? 0 ) < ( $1["activityAt"] as? Double ?? 0 ) }
            let working=agents.filter { ["Working","Waiting"].contains($0["status"] as? String ?? "") }.count
            var group:JSON=["id":root.id,"title":root.title,"project":root.project,"projectKey":root.projectKey,"updatedAt":max(root.updated,latest?["activityAt"] as? Double ?? 0),"subagentCount":agents.count-1,"workingAgents":working,"usage":total.json]
            group["previousUsage"]=window.previous == nil ? NSNull() : previous.json
            if thread != nil { group["agents"]=agents }
            groups.append(group)
        }
        let linked=records.values.filter { $0.subagent && ($0.parent==nil || records[$0.parent ?? ""]==nil) }.count
        return ["groups":groups,"total":grand.json,"previousTotal":window.previous == nil ? NSNull() : previousGrand.json,"matchingCount":window.start==nil ? matches.count : matchingCount,"loadedCount":groups.count,"unlinkedSubagents":linked,"observedAt":window.end,"period":window.json,"previousPeriod":window.previous?.json as Any? ?? NSNull(),"coverage":"Local parent chats and all linked task subagents, including archived descendants. Token totals use usage-record timestamps. Changes compare the selected period with the immediately preceding period of equal length, for the same loaded chats. Chats with usage in either period are included. Undated usage is included only in All time and makes bounded comparisons unavailable. System approval reviewers and voice helpers are excluded. Model, effort and activity show the latest recorded state, which may be outside the selected period; activity is not a live connection check."]
    }
}
