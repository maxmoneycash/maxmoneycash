import Foundation

struct DailyUsageResponse: Codable, Equatable {
    var from: String
    var to: String
    var data: [DailyEntry]

    init(from: String = "", to: String = "", data: [DailyEntry] = []) {
        self.from = from; self.to = to; self.data = data
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.from = try c.decodeIfPresent(String.self, forKey: .from) ?? ""
        self.to = try c.decodeIfPresent(String.self, forKey: .to) ?? ""
        self.data = try c.decodeIfPresent([DailyEntry].self, forKey: .data) ?? []
    }

    private enum CodingKeys: String, CodingKey { case from, to, data }
}

struct DailyEntry: Codable, Equatable, Identifiable {
    var id: String { day }
    var day: String
    var totalTokens: Int
    var billableTotalTokens: Int
    var inputTokens: Int
    var outputTokens: Int
    var cachedInputTokens: Int
    var cacheCreationInputTokens: Int
    var reasoningOutputTokens: Int
    var conversationCount: Int

    init(day: String = "", totalTokens: Int = 0, billableTotalTokens: Int = 0,
         inputTokens: Int = 0, outputTokens: Int = 0, cachedInputTokens: Int = 0,
         cacheCreationInputTokens: Int = 0, reasoningOutputTokens: Int = 0, conversationCount: Int = 0) {
        self.day = day; self.totalTokens = totalTokens; self.billableTotalTokens = billableTotalTokens
        self.inputTokens = inputTokens; self.outputTokens = outputTokens
        self.cachedInputTokens = cachedInputTokens; self.cacheCreationInputTokens = cacheCreationInputTokens
        self.reasoningOutputTokens = reasoningOutputTokens; self.conversationCount = conversationCount
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        day = try c.decodeIfPresent(String.self, forKey: .day) ?? ""
        totalTokens = try c.decodeIfPresent(Int.self, forKey: .totalTokens) ?? 0
        billableTotalTokens = try c.decodeIfPresent(Int.self, forKey: .billableTotalTokens) ?? 0
        inputTokens = try c.decodeIfPresent(Int.self, forKey: .inputTokens) ?? 0
        outputTokens = try c.decodeIfPresent(Int.self, forKey: .outputTokens) ?? 0
        cachedInputTokens = try c.decodeIfPresent(Int.self, forKey: .cachedInputTokens) ?? 0
        cacheCreationInputTokens = try c.decodeIfPresent(Int.self, forKey: .cacheCreationInputTokens) ?? 0
        reasoningOutputTokens = try c.decodeIfPresent(Int.self, forKey: .reasoningOutputTokens) ?? 0
        conversationCount = try c.decodeIfPresent(Int.self, forKey: .conversationCount) ?? 0
    }

    private enum CodingKeys: String, CodingKey {
        case day
        case totalTokens = "total_tokens"
        case billableTotalTokens = "billable_total_tokens"
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case cachedInputTokens = "cached_input_tokens"
        case cacheCreationInputTokens = "cache_creation_input_tokens"
        case reasoningOutputTokens = "reasoning_output_tokens"
        case conversationCount = "conversation_count"
    }
}
