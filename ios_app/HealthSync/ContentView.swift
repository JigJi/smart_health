import SwiftUI

struct ContentView: View {
    @EnvironmentObject var hk: HealthKitManager

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            // Status icon
            Image(systemName: hk.isAuthorized ? "checkmark.circle.fill" : "heart.circle")
                .font(.system(size: 80))
                .foregroundColor(hk.isAuthorized ? .green : .gray)

            Text("สุขภาพดี")
                .font(.title.bold())

            Text(hk.isAuthorized ? "เชื่อมต่อแล้ว ✅" : "กำลังเชื่อมต่อ...")
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
