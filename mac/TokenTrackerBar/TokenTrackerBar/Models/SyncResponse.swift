import Foundation

struct SyncResponse: Codable, Equatable {
    var ok: Bool
    var code: Int?
    var error: String?
    var stdout: String?
    var stderr: String?

    init(ok: Bool = false, code: Int? = nil, error: String? = nil, stdout: String? = nil, stderr: String? = nil) {
        self.ok = ok
        self.code = code
        self.error = error
        self.stdout = stdout
        self.stderr = stderr
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        ok = try container.decodeIfPresent(Bool.self, forKey: .ok) ?? false
        code = try container.decodeIfPresent(Int.self, forKey: .code)
        error = try container.decodeIfPresent(String.self, forKey: .error)
        stdout = try container.decodeIfPresent(String.self, forKey: .stdout)
        stderr = try container.decodeIfPresent(String.self, forKey: .stderr)
    }

    private enum CodingKeys: String, CodingKey {
        case ok, code, error, stdout, stderr
    }
}
