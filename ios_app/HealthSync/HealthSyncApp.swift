import SwiftUI

@main
struct HealthSyncApp: App {
    @StateObject private var healthKit = HealthKitManager()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(healthKit)
                .onAppear {
                    healthKit.requestAuthorization()
                }
        }
    }
}
