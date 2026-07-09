import Foundation

struct ModelBreakdownResponse: Codable, Equatable {
    var from: String
    var to: String
    var days: Int
    var sources: [SourceEntry]
    var pricing: PricingInfo?

    init(from: String = "", to: String = "", days: Int = 0, sources: [SourceEntry] = [], pricing: PricingInfo? = nil) {
        self.from = from; self.to = to; self.days = days; self.sources = sources; self.pricing = pricing
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.from = try c.decodeIfPresent(String.self, forKey: .from) ?? ""
        self.to = try c.decodeIfPresent(String.self, forKey: .to) ?? ""
        self.days = try c.decodeIfPresent(Int.self, forKey: .days) ?? 0
        self.sources = try c.decodeIfPresent([SourceEntry].self, forKey: .sources) ?? []
        self.pricing = try c.decodeIfPresent(PricingInfo.self, forKey: .pricing)
    }

    private enum CodingKeys: String, CodingKey { case from, to, days, sources, pricing }
}

struct SourceEntry: Codable, Equatable {
    var source: String
    var totals: TokenTotals
    var models: [ModelEntry]

    init(source: String = "", totals: TokenTotals = TokenTotals(), models: [ModelEntry] = []) {
        self.source = source; self.totals = totals; self.models = models
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        source = try c.decodeIfPresent(String.self, forKey: .source) ?? ""
        totals = try c.decodeIfPresent(TokenTotals.self, forKey: .totals) ?? TokenTotals()
        models = try c.decodeIfPresent([ModelEntry].self, forKey: .models) ?? []
    }

    private enum CodingKeys: String, CodingKey { case source, totals, models }
}

struct ModelEntry: Codable, Equatable, Identifiable {
    var id: String { modelId }
    var model: String
    var modelId: String
    var totals: TokenTotals

    init(model: String = "", modelId: String = "", totals: TokenTotals = TokenTotals()) {
        self.model = model; self.modelId = modelId; self.totals = totals
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        model = try c.decodeIfPresent(String.self, forKey: .model) ?? ""
        modelId = try c.decodeIfPresent(String.self, forKey: .modelId) ?? ""
        totals = try c.decodeIfPresent(TokenTotals.self, forKey: .totals) ?? TokenTotals()
    }

    private enum CodingKeys: String, CodingKey {
        case model
        case modelId = "model_id"
        case totals
    }
}

struct PricingInfo: Codable, Equatable {
    var model: String
    var pricingMode: String
    var source: String
    var effectiveFrom: String
    var ratesPerMillionUsd: PricingRates?

    init(model: String = "", pricingMode: String = "", source: String = "",
         effectiveFrom: String = "", ratesPerMillionUsd: PricingRates? = nil) {
        self.model = model; self.pricingMode = pricingMode; self.source = source
        self.effectiveFrom = effectiveFrom; self.ratesPerMillionUsd = ratesPerMillionUsd
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        model = try c.decodeIfPresent(String.self, forKey: .model) ?? ""
        pricingMode = try c.decodeIfPresent(String.self, forKey: .pricingMode) ?? ""
        source = try c.decodeIfPresent(String.self, forKey: .source) ?? ""
        effectiveFrom = try c.decodeIfPresent(String.self, forKey: .effectiveFrom) ?? ""
        ratesPerMillionUsd = try c.decodeIfPresent(PricingRates.self, forKey: .ratesPerMillionUsd)
    }

    private enum CodingKeys: String, CodingKey {
        case model, source
        case pricingMode = "pricing_mode"
        case effectiveFrom = "effective_from"
        case ratesPerMillionUsd = "rates_per_million_usd"
    }
}

struct PricingRates: Codable, Equatable {
    var input: String
    var cachedInput: String
    var output: String
    var reasoningOutput: String

    init(input: String = "0", cachedInput: String = "0", output: String = "0", reasoningOutput: String = "0") {
        self.input = input; self.cachedInput = cachedInput; self.output = output; self.reasoningOutput = reasoningOutput
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        input = try c.decodeIfPresent(String.self, forKey: .input) ?? "0"
        cachedInput = try c.decodeIfPresent(String.self, forKey: .cachedInput) ?? "0"
        output = try c.decodeIfPresent(String.self, forKey: .output) ?? "0"
        reasoningOutput = try c.decodeIfPresent(String.self, forKey: .reasoningOutput) ?? "0"
    }

    private enum CodingKeys: String, CodingKey {
        case input, output
        case cachedInput = "cached_input"
        case reasoningOutput = "reasoning_output"
    }
}
