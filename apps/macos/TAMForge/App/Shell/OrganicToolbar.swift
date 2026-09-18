import SwiftUI

struct OrganicToolbar<Trailing: View>: View {
    let breadcrumb: String
    @ViewBuilder let trailing: () -> Trailing

    var body: some View {
        HStack(spacing: Organic.Space.p12) {
            Text(breadcrumb)
                .font(Organic.Font.figtree(.regular, size: 13))
                .foregroundStyle(Organic.Color.muted)
                .lineLimit(1)
            Spacer(minLength: Organic.Space.p16)
            trailing()
        }
        .padding(.horizontal, Organic.Space.p36)
        .frame(height: 52)
        .background(Organic.Color.bg)
        .overlay(alignment: .bottom) { Rectangle().fill(Organic.Color.divider).frame(height: 1) }
    }
}
