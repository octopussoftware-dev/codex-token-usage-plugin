#include "ZstdBridge.h"
#include <stdlib.h>
#include <zstd.h>

/* Bound memory use, support concatenated frames, and never write transcripts to disk. */
uint8_t *cost_zstd_decode(const uint8_t *source, size_t length, size_t *decoded_length) {
    const size_t maximum = 512u * 1024u * 1024u;
    size_t capacity = 1024u * 1024u, used = 0, remaining = 1;
    uint8_t *output = malloc(capacity);
    ZSTD_DStream *stream = ZSTD_createDStream();
    if (!output || !stream) { free(output); ZSTD_freeDStream(stream); return NULL; }
    if (ZSTD_isError(ZSTD_initDStream(stream))) goto failure;
    ZSTD_inBuffer input = {source, length, 0};
    while (input.pos < input.size || remaining != 0) {
        if (used == capacity) {
            if (capacity == maximum) goto failure;
            capacity = capacity > maximum / 2 ? maximum : capacity * 2;
            uint8_t *grown = realloc(output, capacity);
            if (!grown) goto failure;
            output = grown;
        }
        ZSTD_outBuffer target = {output + used, capacity - used, 0};
        size_t before = input.pos;
        remaining = ZSTD_decompressStream(stream, &target, &input);
        if (ZSTD_isError(remaining) || (before == input.pos && target.pos == 0)) goto failure;
        used += target.pos;
    }
    if (remaining != 0) goto failure;
    ZSTD_freeDStream(stream); *decoded_length = used; return output;
failure:
    free(output); ZSTD_freeDStream(stream); return NULL;
}
