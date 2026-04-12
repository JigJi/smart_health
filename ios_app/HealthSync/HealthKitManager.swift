import Foundation
import HealthKit
import Combine

class HealthKitManager: ObservableObject {
    private let store = HKHealthStore()
    private let api = APIClient()

    @Published var isAuthorized = false
    @Published var lastSyncText = "ยังไม่เคย sync"
    @Published var todayHRCount = 0
    @Published var syncStatus = "—"

    // HealthKit types we need
    private let readTypes: Set<HKObjectType> = [
        HKQuantityType(.heartRate),
        HKQuantityType(.heartRateVariabilitySDNN),
        HKQuantityType(.restingHeartRate),
        HKQuantityType(.stepCount),
        HKQuantityType(.activeEnergyBurned),
        HKQuantityType(.oxygenSaturation),
        HKQuantityType(.respiratoryRate),
        HKObjectType.workoutType(),
    ]

    // MARK: - Authorization

    func requestAuthorization() {
        guard HKHealthStore.isHealthDataAvailable() else { return }

        store.requestAuthorization(toShare: nil, read: readTypes) { [weak self] ok, err in
            DispatchQueue.main.async {
                self?.isAuthorized = ok
                if ok {
                    self?.enableBackgroundDelivery()
                    self?.syncNow()
                }
            }
        }
    }

    // MARK: - Background Delivery

    func enableBackgroundDelivery() {
        let types: [HKQuantityType] = [
            HKQuantityType(.heartRate),
            HKQuantityType(.heartRateVariabilitySDNN),
            HKQuantityType(.restingHeartRate),
        ]
        for type in types {
            store.enableBackgroundDelivery(for: type, frequency: .hourly) { _, _ in }
        }

        // Observe each type — iOS will wake us when new data arrives
        for type in types {
            let query = HKObserverQuery(sampleType: type, predicate: nil) { [weak self] _, completionHandler, _ in
                self?.syncNow()
                completionHandler()
            }
            store.execute(query)
        }
    }

    // MARK: - Sync

    func syncNow() {
        DispatchQueue.main.async { self.syncStatus = "กำลัง sync..." }

        let since = Calendar.current.date(byAdding: .hour, value: -25, to: Date())!
        let group = DispatchGroup()

        var lines: [String] = []
        let lock = NSLock()

        // Heart Rate
        group.enter()
        fetchSamples(.heartRate, since: since) { samples in
            let mapped = samples.map { "HR|\(self.iso($0.0))|\(String(format: "%.0f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            DispatchQueue.main.async { self.todayHRCount = samples.count }
            group.leave()
        }

        // HRV
        group.enter()
        fetchSamples(.heartRateVariabilitySDNN, since: since) { samples in
            let mapped = samples.map { "HRV|\(self.iso($0.0))|\(String(format: "%.1f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            group.leave()
        }

        // Resting HR (last 7 days for more data)
        let since7d = Calendar.current.date(byAdding: .day, value: -7, to: Date())!
        group.enter()
        fetchSamples(.restingHeartRate, since: since7d) { samples in
            let mapped = samples.map { "RHR|\(self.iso($0.0))|\(String(format: "%.0f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            group.leave()
        }

        // Steps
        group.enter()
        fetchSamples(.stepCount, since: since) { samples in
            let mapped = samples.map { "STEPS|\(self.iso($0.0))|\(String(format: "%.0f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            group.leave()
        }

        // Workouts
        group.enter()
        fetchWorkouts(since: since) { workouts in
            for w in workouts {
                let type = w.workoutActivityType.name
                let dur = String(format: "%.0f", w.duration / 60)
                let start = self.iso(w.startDate)

                var hrAvg = ""
                var hrMax = ""
                if let stats = w.statistics(for: HKQuantityType(.heartRate)) {
                    if let avg = stats.averageQuantity() {
                        hrAvg = String(format: "%.0f", avg.doubleValue(for: .count().unitDivided(by: .minute())))
                    }
                    if let max = stats.maximumQuantity() {
                        hrMax = String(format: "%.0f", max.doubleValue(for: .count().unitDivided(by: .minute())))
                    }
                }
                let line = "WK|\(type)|\(start)|\(dur)|\(hrAvg)|\(hrMax)"
                lock.lock(); lines.append(line); lock.unlock()
            }
            group.leave()
        }

        group.notify(queue: .main) { [weak self] in
            guard !lines.isEmpty else {
                self?.syncStatus = "ไม่มี data ใหม่"
                return
            }
            let payload = lines.joined(separator: "\n")
            self?.api.postSync(payload: payload) { ok in
                DispatchQueue.main.async {
                    let formatter = DateFormatter()
                    formatter.dateFormat = "HH:mm"
                    self?.lastSyncText = "วันนี้ \(formatter.string(from: Date()))"
                    self?.syncStatus = ok ? "✅ \(lines.count) rows" : "❌ ส่งไม่สำเร็จ"
                }
            }
        }
    }

    // MARK: - HealthKit Queries

    private func fetchSamples(
        _ type: HKQuantityTypeIdentifier,
        since: Date,
        completion: @escaping ([(Date, Double)]) -> Void
    ) {
        let qt = HKQuantityType(type)
        let pred = HKQuery.predicateForSamples(withStart: since, end: Date())
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)

        let unit: HKUnit = {
            switch type {
            case .heartRate, .restingHeartRate:
                return .count().unitDivided(by: .minute())
            case .heartRateVariabilitySDNN:
                return .secondUnit(with: .milli)
            case .stepCount:
                return .count()
            default:
                return .count()
            }
        }()

        let query = HKSampleQuery(
            sampleType: qt, predicate: pred, limit: 1000, sortDescriptors: [sort]
        ) { _, results, _ in
            let samples = (results as? [HKQuantitySample])?.map {
                ($0.startDate, $0.quantity.doubleValue(for: unit))
            } ?? []
            completion(samples)
        }
        store.execute(query)
    }

    private func fetchWorkouts(since: Date, completion: @escaping ([HKWorkout]) -> Void) {
        let pred = HKQuery.predicateForSamples(withStart: since, end: Date())
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)

        let query = HKSampleQuery(
            sampleType: .workoutType(), predicate: pred, limit: 50, sortDescriptors: [sort]
        ) { _, results, _ in
            completion(results as? [HKWorkout] ?? [])
        }
        store.execute(query)
    }

    private func iso(_ date: Date) -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f.string(from: date)
    }
}

// Map workout type to string name
extension HKWorkoutActivityType {
    var name: String {
        switch self {
        case .traditionalStrengthTraining: return "TraditionalStrengthTraining"
        case .walking: return "Walking"
        case .cycling: return "Cycling"
        case .running: return "Running"
        case .elliptical: return "Elliptical"
        case .tableTennis: return "TableTennis"
        case .tennis: return "Tennis"
        case .boxing: return "Boxing"
        case .coreTraining: return "CoreTraining"
        case .dance: return "Dance"
        case .functionalStrengthTraining: return "FunctionalStrengthTraining"
        case .highIntensityIntervalTraining: return "HIIT"
        case .yoga: return "Yoga"
        case .swimming: return "Swimming"
        default: return "Other"
        }
    }
}
