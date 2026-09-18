repo: fgomensoro/tam-forge
branch: main
path: apps/macos/TAMForge

## Last sync
date: 2026-09-18T00:54:18Z

### Updated in this project
- Added the English classes view (list, editor, transcript) to the redesign
- Recreated the stock SwiftUI shell (sidebar, Today, Activity workspace) in `TAM Forge — Current.dc.html`
- Redesigned the whole Mac app on the Organic system (dark warm ground) in `TAM Forge — Mac.dc.html`

## Screen map
| Screen | Repo files |
| --- | --- |
| Shell / sidebar / toolbar | apps/macos/TAMForge/App/TAMForgeApp.swift, Core/Diagnostics/GlobalBanner.swift, Features/Notifications/NotificationView.swift |
| Today | apps/macos/TAMForge/Features/Today/TodayView.swift, App/NativeUIFixtures.swift |
| Activity workspace | apps/macos/TAMForge/Features/Activities/ActivityWorkspaceView.swift |
| Cards | apps/macos/TAMForge/Features/Cards/CardsView.swift |
| Progress | apps/macos/TAMForge/Features/Progress/ProgressView.swift |
| Interviews | apps/macos/TAMForge/Features/Interviews/InterviewsView.swift |
| Evidence | apps/macos/TAMForge/Features/Evidence/EvidenceLedgerView.swift |
| Recording | apps/macos/TAMForge/Features/Recording/RecordingView.swift |
| Roadmaps | apps/macos/TAMForge/Features/Roadmaps/RoadmapAdministrationView.swift |
| English classes | apps/macos/TAMForge/Features/Classes/ClassesView.swift, Features/Classes/ClassModels.swift |
