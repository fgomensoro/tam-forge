import SwiftUI

enum GlobalBanner: Equatable, Sendable {
    case offline
    case retrying
    case permission
    case processing
    case actionRequired

    var title: String {
        switch self {
        case .offline:
            "You're offline"
        case .retrying:
            "Reconnecting"
        case .permission:
            "Sign in needed"
        case .processing:
            "Processing update"
        case .actionRequired:
            "Action needed"
        }
    }

    var message: String {
        switch self {
        case .offline:
            "We'll refresh when your connection returns."
        case .retrying:
            "Trying to restore live updates."
        case .permission:
            "Your session has ended. Sign in again to continue."
        case .processing:
            "Your latest update is being processed."
        case .actionRequired:
            "Review the related item to continue."
        }
    }

    var symbolName: String {
        switch self {
        case .offline:
            "wifi.slash"
        case .retrying:
            "arrow.trianglehead.2.clockwise.rotate.90"
        case .permission:
            "lock.fill"
        case .processing:
            "arrow.triangle.2.circlepath"
        case .actionRequired:
            "exclamationmark.triangle.fill"
        }
    }
}

struct GlobalBannerView: View {
    let banner: GlobalBanner

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: banner.symbolName)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(banner.title).font(.headline)
                Text(banner.message).font(.subheadline)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 10))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(banner.title). \(banner.message)")
        .accessibilityIdentifier("\(identifier)Banner")
    }

    private var identifier: String {
        switch banner {
        case .offline: "offline"
        case .retrying: "retrying"
        case .permission: "permission"
        case .processing: "processing"
        case .actionRequired: "actionRequired"
        }
    }
}
