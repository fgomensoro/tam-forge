import SwiftUI

struct SignInView: View {
    let environmentLabel: String
    let banner: GlobalBanner?
    let onSignIn: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Organic.Space.p18) {
            Spacer(minLength: 0)
            appIcon
            Text("TAM Forge")
                .font(Organic.Font.figtree(.semibold, size: 28))
                .foregroundStyle(Organic.Color.text)
                .accessibilityIdentifier("shellTitle")
            Text("Sign in to continue your study workspace. \(environmentLabel).")
                .font(Organic.Font.figtree(.regular, size: 14))
                .foregroundStyle(Organic.Color.muted)
                .accessibilityIdentifier("environmentLabel")
            if let banner { GlobalBannerView(banner: banner).organicCard(radius: Organic.Radius.r24) }
            Button {
                onSignIn()
            } label: {
                HStack(spacing: Organic.Space.p8) {
                    Image(systemName: "chevron.left.forwardslash.chevron.right").font(.system(size: 16, weight: .bold))
                    Text("Sign in with GitHub")
                }
            }
            .buttonStyle(OrganicPrimaryButtonStyle())
            .accessibilityIdentifier("signInButton")
            .keyboardShortcut(.defaultAction)
            Text("PKCE · 15-minute token in memory · refresh token in your Keychain only.")
                .font(Organic.Font.figtree(.regular, size: 12))
                .foregroundStyle(Organic.Color.faint)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 48)
        .padding(.bottom, Organic.Space.p40)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .background(Organic.Color.bg)
    }

    /// Stands in for the real icon until stage 8 adds the asset catalog.
    private var appIcon: some View {
        RoundedRectangle(cornerRadius: 16, style: .continuous)
            .fill(Organic.Color.neutral900)
            .frame(width: 72, height: 72)
            .overlay {
                Circle().fill(Organic.Color.accent).frame(width: 48, height: 48)
                    .overlay(alignment: .center) {
                        Circle().fill(Organic.Color.accent2).frame(width: 27, height: 27).offset(x: -3, y: -3)
                    }
            }
    }
}
