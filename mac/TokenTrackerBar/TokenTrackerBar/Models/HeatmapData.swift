import Foundation

struct HeatmapResponse: Codable, Equatable {
    var from: String
    var to: String
    var weekStartsOn: String
    var activeDays: Int
    var streakDays: Int
    var weeks: [[HeatmapCell?]]

    init(from: String = "", to: String = "", weekStartsOn: String = "sun",
         activeDays: Int = 0, streakDays: Int = 0, weeks: [[HeatmapCell?]] = []) {
        self.from = from; self.to = to; self.weekStartsOn = weekStartsOn
        self.activeDays = activeDays; self.streakDays = streakDays; self.weeks = weeks
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        from = try c.decodeIfPresent(String.self, forKey: .from) ?? ""
        to = try c.decodeIfPresent(String.self, forKey: .to) ?? ""
        weekStartsOn = try c.decodeIfPresent(String.self, forKey: .weekStartsOn) ?? "sun"
        activeDays = try c.decodeIfPresent(Int.self, forKey: .activeDays) ?? 0
        streakDays = try c.decodeIfPresent(Int.self, forKey: .streakDays) ?? 0
        weeks = try c.decodeIfPresent([[HeatmapCell?]].self, forKey: .weeks) ?? []
    }

    private enum CodingKeys: String, CodingKey {
        case from, to, weeks
        case weekStartsOn = "week_starts_on"
        case activeDays = "active_days"
        case streakDays = "streak_days"
    }
}

struct HeatmapCell: Codable, Equatable {
    var day: String
    var totalTokens: Int
    var billableTotalTokens: Int
    var level: Int

    init(day: String = "", totalTokens: Int = 0, billableTotalTokens: Int = 0, level: Int = 0) {
        self.day = day; self.totalTokens = totalTokens
        self.billableTotalTokens = billableTotalTokens; self.level = level
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        day = try c.decodeIfPresent(String.self, forKey: .day) ?? ""
        totalTokens = try c.decodeIfPresent(Int.self, forKey: .totalTokens) ?? 0
        billableTotalTokens = try c.decodeIfPresent(Int.self, forKey: .billableTotalTokens) ?? 0
        level = try c.decodeIfPresent(Int.self, forKey: .level) ?? 0
    }

    private enum CodingKeys: String, CodingKey {
        case day
        case totalTokens = "total_tokens"
        case billableTotalTokens = "billable_total_tokens"
        case level
    }
}
