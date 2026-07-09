import AppKit
import Foundation

enum DashboardBrowserOpener {
    private enum Browser: String, CaseIterable {
        case chrome = "Google Chrome"
        case safari = "Safari"
        case edge = "Microsoft Edge"
        case arc = "Arc"

        var bundleHints: [String] {
            switch self {
            case .chrome:
                ["chrome"]
            case .safari:
                ["safari"]
            case .edge:
                ["edgemac"]
            case .arc:
                ["thebrowser", "arc"]
            }
        }

        var usesChromeTabModel: Bool {
            switch self {
            case .chrome, .edge, .arc:
                true
            case .safari:
                false
            }
        }
    }

    static func openDashboard(from source: String? = nil) {
        let matchURL = normalizedDashboardURL
        let openURL = dashboardOpenURL(from: source)

        guard !runReuseScript(matchURL: matchURL, openURL: openURL) else {
            return
        }

        if let url = URL(string: openURL) {
            NSWorkspace.shared.open(url)
        }
    }

    private static var normalizedDashboardURL: String {
        guard let url = URL(string: Constants.serverBaseURL) else {
            return Constants.serverBaseURL
        }
        return url.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    private static func dashboardOpenURL(from source: String?) -> String {
        guard let source, !source.isEmpty else {
            return Constants.serverBaseURL
        }
        var components = URLComponents(string: Constants.serverBaseURL)
        components?.queryItems = [URLQueryItem(name: "from", value: source)]
        return components?.url?.absoluteString ?? Constants.serverBaseURL
    }

    private static func runReuseScript(matchURL: String, openURL: String) -> Bool {
        let browsers = browserList()
        let listLiteral = browsers.map { "\"\($0.rawValue)\"" }.joined(separator: ", ")
        let chromeFamily = browsers
            .filter(\.usesChromeTabModel)
            .map { "\"\($0.rawValue)\"" }
            .joined(separator: ", ")
        let escapedMatchURL = appleScriptString(matchURL)
        let escapedOpenURL = appleScriptString(openURL)
        let script = """
        tell application "System Events"
          set browserList to {
        \(listLiteral)}
          set chromeFamily to {
        \(chromeFamily)}
          set runningBrowser to ""
          repeat with b in browserList
            if exists process (b as text) then
              set runningBrowser to (b as text)
              exit repeat
            end if
          end repeat
        end tell

        if runningBrowser is "" then
          return "not-found"
        else if chromeFamily contains runningBrowser then
          tell application runningBrowser
            repeat with w in windows
              set tabIndex to 0
              repeat with t in tabs of w
                set tabIndex to tabIndex + 1
                if URL of t starts with "\(escapedMatchURL)" then
                  set active tab index of w to tabIndex
                  set index of w to 1
                  reload t
                  activate
                  return "found"
                end if
              end repeat
            end repeat
            open location "\(escapedOpenURL)"
            activate
            return "opened"
          end tell
        else if runningBrowser is "Safari" then
          tell application "Safari"
            repeat with w in windows
              repeat with t in tabs of w
                if URL of t starts with "\(escapedMatchURL)" then
                  set current tab of w to t
                  set index of w to 1
                  do JavaScript "location.reload()" in t
                  activate
                  return "found"
                end if
              end repeat
            end repeat
            open location "\(escapedOpenURL)"
            activate
            return "opened"
          end tell
        else
          return "not-found"
        end if
        """

        var error: NSDictionary?
        let result = NSAppleScript(source: script)?.executeAndReturnError(&error).stringValue
        return error == nil && (result == "found" || result == "opened")
    }

    private static func browserList() -> [Browser] {
        let all = Browser.allCases
        guard let defaultBrowser = detectDefaultBrowser() else {
            return all
        }
        return [defaultBrowser] + all.filter { $0 != defaultBrowser }
    }

    private static func detectDefaultBrowser() -> Browser? {
        guard let httpsURL = URL(string: "https://example.com"),
              let appURL = NSWorkspace.shared.urlForApplication(toOpen: httpsURL),
              let bundleIdentifier = Bundle(url: appURL)?.bundleIdentifier?.lowercased() else {
            return nil
        }
        return Browser.allCases.first { browser in
            browser.bundleHints.contains { bundleIdentifier.contains($0) }
        }
    }

    private static func appleScriptString(_ value: String) -> String {
        value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
    }
}
