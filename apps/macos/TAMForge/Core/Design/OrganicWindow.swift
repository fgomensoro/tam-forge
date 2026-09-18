import SwiftUI

extension Organic {
    enum Window {
        static let defaultSize = CGSize(width: 1280, height: 820)
        /// The shipped minimum stays the hard floor; layouts must survive it.
        static let minimumSize = CGSize(width: 900, height: 640)
        /// Traffic lights sit at y 52, so sidebar content starts below them.
        static let trafficLightInset: CGFloat = 52
    }
}

extension Scene {
    /// Hidden title bar, Organic sizing, dark-only. The palette has no light values.
    func organicWindowChrome() -> some Scene {
        windowStyle(.hiddenTitleBar)
            .defaultSize(width: Organic.Window.defaultSize.width, height: Organic.Window.defaultSize.height)
    }
}
