//
//  HealthSyncApp.swift
//  HealthSync
//
//  Created by Jirawat Sangthong on 12/4/2569 BE.
//

import SwiftUI

@main
struct HealthSyncApp: App {
    @StateObject private var healthKit = HealthKitManager()
    @Environment(\.scenePhase) private var scenePhase
    @AppStorage("hasOnboarded") private var hasOnboarded = false

    var body: some Scene {
        WindowGroup {
            Group {
                if hasOnboarded {
                    ContentView()
                        .environmentObject(healthKit)
                        .onAppear {
                            // Silent re-check — iOS will only prompt if readTypes grew
                            healthKit.requestAuthorization()
                        }
                } else {
                    OnboardingView {
                        healthKit.requestAuthorization()
                        hasOnboarded = true
                    }
                }
            }
            .onChange(of: scenePhase) { _, newPhase in
                if newPhase == .active && healthKit.isAuthorized {
                    // First launch → backfill 5y. Subsequent launches → incremental sync.
                    healthKit.initialBackfillIfNeeded()
                }
            }
        }
    }
}
