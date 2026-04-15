//
//  ContentView.swift
//  HealthSync
//
//  Created by Jirawat Sangthong on 12/4/2569 BE.
//

import SwiftUI

struct ContentView: View {
    @EnvironmentObject var hk: HealthKitManager
    @Environment(\.scenePhase) private var scenePhase

    // Production: Tailscale Funnel → Windows server frontend (Next.js)
    // uid query param lets the frontend forward X-User-Id to backend
    var dashboardURL: String {
        "https://voizely-backend.tailb8d083.ts.net:8443?uid=\(APIClient.userId())"
    }

    @State private var webReloadTrigger = 0

    var body: some View {
        ZStack(alignment: .top) {
            TabView {
                // Tab 1: Dashboard (WebView)
                WebViewContainer(url: URL(string: dashboardURL)!, reloadTrigger: webReloadTrigger)
                    .ignoresSafeArea()
                    .tabItem {
                        Image(systemName: "heart.text.square")
                        Text("สรุป")
                    }

                // Tab 2: Sync status
                SyncView()
                    .environmentObject(hk)
                    .tabItem {
                        Image(systemName: "arrow.triangle.2.circlepath")
                        Text("Sync")
                    }
            }
            .tint(.green)

            // Sync / backfill banner overlay — ชนิด native, ลอยบนสุด
            if hk.isBackfilling {
                SyncBanner(label: hk.backfillStatus.isEmpty ? "กำลังตั้งค่าครั้งแรก…" : hk.backfillStatus,
                           progress: hk.backfillProgress)
                    .padding(.horizontal, 16)
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
            } else if hk.isSyncing {
                SyncBanner(label: "Syncing data…", progress: hk.syncProgress)
                    .padding(.horizontal, 16)
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.25), value: hk.isSyncing)
        .animation(.easeInOut(duration: 0.25), value: hk.isBackfilling)
        .onChange(of: hk.syncCompletedCount) { _, _ in
            webReloadTrigger += 1
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                webReloadTrigger += 1
            }
        }
    }
}

struct OnboardingView: View {
    let onAccept: () -> Void

    var body: some View {
        ZStack {
            // Soft off-white background with subtle gradient
            LinearGradient(
                colors: [
                    Color(red: 0.99, green: 0.99, blue: 0.98),
                    Color(red: 0.96, green: 0.97, blue: 0.96),
                ],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()

            VStack(spacing: 0) {
                Spacer()

                // Icon
                Image(systemName: "heart.text.square.fill")
                    .font(.system(size: 76, weight: .regular))
                    .foregroundStyle(
                        LinearGradient(
                            colors: [Color(red: 0.19, green: 0.82, blue: 0.35),
                                     Color(red: 0.12, green: 0.60, blue: 0.25)],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
                    .shadow(color: Color.green.opacity(0.25), radius: 18, y: 8)

                Spacer().frame(height: 28)

                // Title
                Text("livvv")
                    .font(.system(size: 38, weight: .bold))
                    .foregroundColor(.black)

                Spacer().frame(height: 10)

                // Subtitle
                Text("ผู้ช่วยวิเคราะห์สุขภาพจาก Apple Health")
                    .font(.system(size: 16))
                    .foregroundColor(.black.opacity(0.5))
                    .multilineTextAlignment(.center)

                Spacer().frame(height: 48)

                // Bullet points
                VStack(alignment: .leading, spacing: 20) {
                    BulletRow(icon: "heart.fill",
                              text: "ติดตามความพร้อมของร่างกายรายวัน")
                    BulletRow(icon: "moon.stars.fill",
                              text: "วิเคราะห์การนอน หัวใจ และการฟื้นตัว")
                    BulletRow(icon: "lock.shield.fill",
                              text: "ข้อมูลเก็บในเครื่องคุณเท่านั้น")
                }
                .padding(.horizontal, 36)

                Spacer()

                // CTA
                VStack(spacing: 14) {
                    Button(action: onAccept) {
                        Text("เริ่มใช้งาน")
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundColor(.white)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 17)
                            .background(Color.black)
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                            .shadow(color: .black.opacity(0.15), radius: 14, y: 6)
                    }

                    Text("หน้าต่างถัดไปจะขอสิทธิ์เข้าถึง Apple Health — แตะ \"Turn On All\" เพื่อใช้งานเต็มที่")
                        .font(.system(size: 12))
                        .foregroundColor(.black.opacity(0.4))
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 12)
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 40)
            }
        }
        .preferredColorScheme(.light)  // ล็อกให้สว่างเสมอ แม้ระบบตั้ง dark mode
    }
}

struct BulletRow: View {
    let icon: String
    let text: String

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 15, weight: .semibold))
                .foregroundColor(Color(red: 0.19, green: 0.82, blue: 0.35))
                .frame(width: 30, height: 30)
                .background(Color(red: 0.19, green: 0.82, blue: 0.35).opacity(0.12))
                .clipShape(Circle())

            Text(text)
                .font(.system(size: 15))
                .foregroundColor(.black.opacity(0.85))

            Spacer()
        }
    }
}

struct SyncBanner: View {
    let label: String
    let progress: Double  // 0.0 – 1.0
    @State private var rotation = 0.0

    var body: some View {
        HStack(spacing: 12) {
            Text(label)
                .font(.system(size: 15, weight: .medium))
                .foregroundColor(.white.opacity(0.9))

            Spacer()

            Text("\(Int(progress * 100))%")
                .font(.system(size: 15, weight: .semibold))
                .foregroundColor(.white.opacity(0.9))
                .monospacedDigit()

            Image(systemName: "arrow.triangle.2.circlepath")
                .font(.system(size: 14, weight: .semibold))
                .foregroundColor(.white.opacity(0.85))
                .rotationEffect(.degrees(rotation))
                .onAppear {
                    withAnimation(.linear(duration: 1).repeatForever(autoreverses: false)) {
                        rotation = 360
                    }
                }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial)
        .clipShape(Capsule())
        .shadow(color: .black.opacity(0.35), radius: 10, y: 2)
        .animation(.easeOut(duration: 0.3), value: progress)
    }
}

struct SyncView: View {
    @EnvironmentObject var hk: HealthKitManager

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            Image(systemName: hk.isAuthorized ? "checkmark.circle.fill" : "heart.circle")
                .font(.system(size: 80))
                .foregroundColor(hk.isAuthorized ? .green : .gray)

            Text("livvv")
                .font(.title.bold())

            Text(hk.isAuthorized ? "เชื่อมต่อแล้ว" : "กำลังเชื่อมต่อ...")
                .foregroundColor(.secondary)

            if hk.isAuthorized {
                VStack(alignment: .leading, spacing: 8) {
                    InfoRow(label: "Sync ล่าสุด", value: hk.lastSyncText)
                    InfoRow(label: "HR samples วันนี้", value: "\(hk.todayHRCount)")
                    InfoRow(label: "Status", value: hk.syncStatus)
                }
                .padding()
                .background(Color(.systemGray6))
                .cornerRadius(12)

                Button(action: { hk.syncNow() }) {
                    Label("Sync ตอนนี้", systemImage: "arrow.triangle.2.circlepath")
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.green.opacity(0.15))
                        .cornerRadius(12)
                }
            }

            Spacer()

            Text("แอพนี้ทำงานเบื้องหลังอัตโนมัติ\nไม่ต้องเปิดอีก — แต่อย่าลบ")
                .font(.caption)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(32)
    }
}

struct InfoRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack {
            Text(label)
                .foregroundColor(.secondary)
                .font(.subheadline)
            Spacer()
            Text(value)
                .font(.subheadline.bold())
        }
    }
}
