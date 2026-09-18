import SwiftUI

extension Organic {
    enum Window {
        static let defaultSize = CGSize(width: 1280, height: 820)
        /// The shipped minimum stays the hard floor; layouts must survive it.
        static let minimumSize = CGSize(width: 900, height: 640)
        /// Traffic lights sit at y 52, so sidebar content starts below them.
        static let trafficLightInset: CGFloat = 52
        /// `.hiddenTitleBar` hides the title bar but still reserves its safe area, and SwiftUI
        /// adds that strip to whatever minimum the content declares. The shell draws into the
        /// strip itself, so its own minimum is `minimumSize` less this: declaring the full 640
        /// gives a window that stops at 672. AppKit reports 32 on macOS 26; if a future release
        /// changes the title bar, the floor moves by that difference and nothing else.
        static let titleBarSafeArea: CGFloat = 32
    }
}

extension Scene {
    /// Hidden title bar, Organic sizing, dark-only. The palette has no light values.
    func organicWindowChrome() -> some Scene {
        windowStyle(.hiddenTitleBar)
            .defaultSize(width: Organic.Window.defaultSize.width, height: Organic.Window.defaultSize.height)
    }
}
