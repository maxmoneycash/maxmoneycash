import SwiftUI

struct TopModelsView: View {
    let models: [TopModel]

    var body: some View {
        if !models.isEmpty {
            VStack(alignment: .leading, spacing: 7) {
                SectionHeader(title: Strings.topModelsTitle)
                ForEach(Array(models.enumerated()), id: \.element.id) { index, model in
                    HStack(spacing: 5) {
                        Circle()
                            .fill(Color.modelDot(index: index))
                            .frame(width: 5, height: 5)
                        Text(model.name)
                            .font(.system(.caption, design: .default))
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer(minLength: 4)
                        Text(TokenFormatter.formatCompact(model.tokens))
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.secondary)
                        Text(model.percent + "%")
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.tertiary)
                            .frame(width: 38, alignment: .trailing)
                    }
                    // Proportional backdrop so share-of-total scans visually,
                    // not just as a number column.
                    .background(alignment: .leading) {
                        GeometryReader { geo in
                            RoundedRectangle(cornerRadius: 3)
                                .fill(Color.modelDot(index: index).opacity(0.12))
                                .frame(width: geo.size.width * CGFloat(min(max((Double(model.percent) ?? 0) / 100, 0), 1)))
                        }
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel(
                        Strings.topModelAccessibility(
                            name: model.name,
                            source: model.source,
                            tokens: TokenFormatter.formatCompact(model.tokens),
                            percent: model.percent
                        )
                    )
                }
            }
        }
    }

}
