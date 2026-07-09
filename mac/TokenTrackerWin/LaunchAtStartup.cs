using System.IO;
using Microsoft.Win32;

namespace TokenTrackerWin;

/// <summary>
/// Windows counterpart of <c>LaunchAtLoginManager.swift</c>. Uses the per-user
/// HKCU Run key (no admin rights, no scheduled task) so toggling never elevates.
/// </summary>
internal static class LaunchAtStartup
{
    private const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";

    /// <summary>
    /// Passed on the auto-start command line so the app can tell a boot-time launch
    /// (stay quietly in the tray) from a manual launch (pop the dashboard open).
    /// </summary>
    public const string StartupArgument = "--startup";

    private static string ExecutablePath =>
        Environment.ProcessPath ?? Application.ExecutablePath;

    public static bool IsEnabled
    {
        get
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, writable: false);
            var value = key?.GetValue(Constants.StartupRegistryValueName) as string;
            if (string.IsNullOrEmpty(value)) return false;
            // Only "on" if the registered command's executable is exactly this exe. Extract
            // the path (the value also carries StartupArgument) and compare it precisely —
            // a substring match would false-positive on any command containing this path.
            var registeredPath = ExtractExecutablePath(value);
            return registeredPath is not null && PathsEqual(registeredPath, ExecutablePath);
        }
    }

    /// <summary>Pull the executable out of a Run-key command (handles a quoted path with
    /// trailing arguments, or an unquoted path up to the first space).</summary>
    private static string? ExtractExecutablePath(string command)
    {
        command = command.Trim();
        if (command.Length == 0) return null;
        if (command[0] == '"')
        {
            var close = command.IndexOf('"', 1);
            return close > 1 ? command[1..close] : null;
        }
        var space = command.IndexOf(' ');
        return space >= 0 ? command[..space] : command;
    }

    private static bool PathsEqual(string a, string b)
    {
        try { return string.Equals(Path.GetFullPath(a), Path.GetFullPath(b), StringComparison.OrdinalIgnoreCase); }
        catch { return string.Equals(a, b, StringComparison.OrdinalIgnoreCase); }
    }

    public static void Enable()
    {
        using var key = Registry.CurrentUser.CreateSubKey(RunKeyPath, writable: true);
        // Quote the path so spaces in the install dir don't split the command, and tag
        // the launch so we start minimized to the tray instead of popping the window.
        key?.SetValue(Constants.StartupRegistryValueName, $"\"{ExecutablePath}\" {StartupArgument}");
    }

    public static void Disable()
    {
        using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, writable: true);
        if (key?.GetValue(Constants.StartupRegistryValueName) is not null)
            key.DeleteValue(Constants.StartupRegistryValueName, throwOnMissingValue: false);
    }

    public static void Toggle()
    {
        if (IsEnabled) Disable();
        else Enable();
    }
}
