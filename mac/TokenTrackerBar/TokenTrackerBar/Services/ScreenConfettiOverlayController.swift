import AppKit
import SwiftUI
import Vortex

/// Full-screen celebration: a two-stage firework (rocket rises → bursts on death,
/// with sparkle trails) using the Vortex particle library's `.fireworks` preset —
/// the same engine CodexBar builds its celebration on. An optional text toast
/// names what reset.
///
/// Each screen gets a borderless, click-through `NSPanel` floating at the
/// status-bar level across all Spaces. Panels never take focus or mouse events,
/// so the user keeps working underneath. The show tears itself down after a few
/// seconds.
@MainActor
final class ScreenConfettiOverlayController {

    private var panels: [NSPanel] = []
    private var dismissTask: Task<Void, Never>?
    private let lifetime: TimeInterval = 5.0

    /// Fire the celebration. `message`, when present, is shown as a fading toast.
    func play(message: String?) {
        guard panels.isEmpty else { return }            // already celebrating — ignore re-entry
        let screens = NSScreen.screens
        guard !screens.isEmpty else { return }

        for screen in screens {
            let panel = makePanel(for: screen)
            // Toast only on the screen with the menu bar (primary), to avoid N copies.
            let showToast = (screen == NSScreen.main)
            let host = NSHostingView(rootView: FireworkOverlayView(message: showToast ? message : nil))
            host.frame = CGRect(origin: .zero, size: screen.frame.size)
            host.wantsLayer = true
            host.layer?.backgroundColor = NSColor.clear.cgColor
            panel.contentView = host
            panel.orderFrontRegardless()
            panels.append(panel)
        }

        dismissTask = Task { [weak self, lifetime] in
            try? await Task.sleep(nanoseconds: UInt64(lifetime * 1_000_000_000))
            self?.dismiss()
        }
    }

    func dismiss() {
        dismissTask?.cancel()
        dismissTask = nil
        for panel in panels {
            panel.orderOut(nil)
            panel.close()
        }
        panels.removeAll()
    }

    private func makePanel(for screen: NSScreen) -> NSPanel {
        let panel = ClickThroughPanel(
            contentRect: screen.frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false,
            screen: screen
        )
        panel.level = .statusBar
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle, .stationary]
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = false
        panel.ignoresMouseEvents = true
        panel.isMovable = false
        panel.isReleasedWhenClosed = false
        panel.hidesOnDeactivate = false
        panel.setFrame(screen.frame, display: false)
        return panel
    }
}

/// Borderless panel that never steals focus or mouse — a transparent overlay.
private final class ClickThroughPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
    override var acceptsFirstResponder: Bool { false }
}

/// Vortex fireworks + an optional fading toast banner near the top.
private struct FireworkOverlayView: View {
    let message: String?
    @State private var toastShown = false

    var body: some View {
        ZStack(alignment: .top) {
            Color.clear
            VortexView(.fireworks)
                .allowsHitTesting(false)

            if let message {
                Text(message)
                    .font(.system(.title3, design: .rounded).weight(.semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 18)
                    .padding(.vertical, 10)
                    .background(.black.opacity(0.72), in: Capsule())
                    .overlay(Capsule().stroke(.white.opacity(0.12), lineWidth: 1))
                    .shadow(color: .black.opacity(0.35), radius: 12, y: 4)
                    .padding(.top, 64)
                    .opacity(toastShown ? 1 : 0)
                    .scaleEffect(toastShown ? 1 : 0.92)
                    .allowsHitTesting(false)
                    .onAppear {
                        withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) { toastShown = true }
                        DispatchQueue.main.asyncAfter(deadline: .now() + 3.2) {
                            withAnimation(.easeOut(duration: 0.6)) { toastShown = false }
                        }
                    }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
