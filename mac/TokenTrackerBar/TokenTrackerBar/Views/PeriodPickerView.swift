import SwiftUI

struct PeriodPickerView: View {
    @Binding var selection: DateHelpers.Period
    let onChange: (DateHelpers.Period) -> Void
    @State private var cursorPushedFor: DateHelpers.Period?

    var body: some View {
        HStack(spacing: 10) {
            ForEach(DateHelpers.Period.allCases) { period in
                Button {
                    onChange(period)
                } label: {
                    Text(period.label)
                        .font(.caption2)
                        .modifier(FontWeightModifier(weight: selection == period ? .semibold : .regular))
                        .foregroundStyle(selection == period ? .primary : .tertiary)
                        // Enlarged hit target: caption2 glyphs alone are too small to click.
                        .padding(.horizontal, 4)
                        .padding(.vertical, 4)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .onHover { hovering in
                    if hovering {
                        if cursorPushedFor != period {
                            if cursorPushedFor != nil {
                                NSCursor.pop()
                            }
                            NSCursor.pointingHand.push()
                            cursorPushedFor = period
                        }
                    } else if cursorPushedFor == period {
                        NSCursor.pop()
                        cursorPushedFor = nil
                    }
                }
            }
        }
        .onDisappear {
            if cursorPushedFor != nil {
                NSCursor.pop()
                cursorPushedFor = nil
            }
        }
    }
}
