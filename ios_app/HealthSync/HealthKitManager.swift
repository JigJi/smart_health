//
//  HealthKitManager.swift
//  HealthSync
//
//  Created by Jirawat Sangthong on 12/4/2569 BE.
//

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
    @Published var isSyncing = false
    @Published var syncCompletedCount = 0
    @Published var syncProgress: Double = 0.0  // 0.0 – 1.0

    // Initial backfill — runs once on first install to seed 5 years of history
    @Published var isBackfilling = false
    @Published var backfillProgress: Double = 0.0
    @Published var backfillStatus = ""

    // Sync throttle — don't re-sync if we synced less than this ago.
    // 5 min: short enough that opening the app shows near-live HRV/stress,
    // long enough to prevent rapid-fire sync from scenePhase flapping
    // (open/close/open within seconds won't spam the backend or HealthKit).
    private var lastSyncAt: Date?
    private let syncMinInterval: TimeInterval = 300   // 5 minutes

    // Request permission for ALL types we might ever use — ask once, never prompt again.
    // เหตุผล: ถ้าเพิ่ม type ใหม่ภายหลัง iOS จะต้องขอใหม่ ผู้ใช้จะรู้สึกรำคาญ
    private let readTypes: Set<HKObjectType> = [
        // Heart & vitals
        HKQuantityType(.heartRate),
        HKQuantityType(.heartRateVariabilitySDNN),
        HKQuantityType(.restingHeartRate),
        HKQuantityType(.walkingHeartRateAverage),
        HKQuantityType(.heartRateRecoveryOneMinute),
        HKQuantityType(.oxygenSaturation),
        HKQuantityType(.respiratoryRate),
        HKQuantityType(.bodyTemperature),
        HKQuantityType(.appleSleepingWristTemperature),
        HKQuantityType(.bloodPressureSystolic),
        HKQuantityType(.bloodPressureDiastolic),
        HKQuantityType(.vo2Max),

        // Activity
        HKQuantityType(.stepCount),
        HKQuantityType(.distanceWalkingRunning),
        HKQuantityType(.distanceCycling),
        HKQuantityType(.distanceSwimming),
        HKQuantityType(.flightsClimbed),
        HKQuantityType(.activeEnergyBurned),
        HKQuantityType(.basalEnergyBurned),
        HKQuantityType(.appleExerciseTime),
        HKQuantityType(.appleStandTime),

        // Body composition
        HKQuantityType(.bodyMass),
        HKQuantityType(.bodyMassIndex),
        HKQuantityType(.bodyFatPercentage),
        HKQuantityType(.leanBodyMass),
        HKQuantityType(.height),
        HKQuantityType(.waistCircumference),

        // Nutrition (common)
        HKQuantityType(.dietaryWater),
        HKQuantityType(.dietaryEnergyConsumed),

        // Category types
        HKCategoryType(.sleepAnalysis),
        HKCategoryType(.mindfulSession),

        // Workouts
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
                    // First install → 5y backfill. Re-launches → incremental sync.
                    self?.initialBackfillIfNeeded()
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

    func syncNow(force: Bool = false) {
        // Run entire check-and-set atomically on main queue to avoid race
        // from multiple scenePhase / observer callbacks firing concurrently
        if Thread.isMainThread {
            _syncNowInternal(force: force)
        } else {
            DispatchQueue.main.async { self._syncNowInternal(force: force) }
        }
    }

    private func _syncNowInternal(force: Bool) {
        // Prevent concurrent syncs (atomic on main thread)
        if isSyncing { return }

        // Throttle: skip if recent sync unless forced
        if !force, let last = lastSyncAt,
           Date().timeIntervalSince(last) < syncMinInterval {
            // Just refresh dashboard — no actual HealthKit pull needed
            syncCompletedCount += 1
            return
        }

        isSyncing = true
        syncProgress = 0.0
        syncStatus = "กำลัง sync..."
        lastSyncAt = Date()

        // Counter-based progress: phasesCompleted/totalPhases, clamped to 1.0
        // (old accumulator pattern could overflow if guard ever leaked → 539% bug)
        // 10 phases: 9 fetches (HR/HRV/RHR/Steps/Cal/SpO2/RR/Sleep/Workouts) + 1 post
        var phasesCompleted = 0
        let totalPhases = 10
        let bumpProgress: () -> Void = {
            DispatchQueue.main.async {
                phasesCompleted += 1
                self.syncProgress = min(1.0, Double(phasesCompleted) / Double(totalPhases))
            }
        }

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
            bumpProgress()
            group.leave()
        }

        // HRV
        group.enter()
        fetchSamples(.heartRateVariabilitySDNN, since: since) { samples in
            let mapped = samples.map { "HRV|\(self.iso($0.0))|\(String(format: "%.1f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            bumpProgress()
            group.leave()
        }

        // Resting HR (last 7 days for more data)
        let since7d = Calendar.current.date(byAdding: .day, value: -7, to: Date())!
        group.enter()
        fetchSamples(.restingHeartRate, since: since7d) { samples in
            let mapped = samples.map { "RHR|\(self.iso($0.0))|\(String(format: "%.0f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            bumpProgress()
            group.leave()
        }

        // Steps
        group.enter()
        fetchSamples(.stepCount, since: since) { samples in
            let mapped = samples.map { "STEPS|\(self.iso($0.0))|\(String(format: "%.0f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            bumpProgress()
            group.leave()
        }

        // Active Energy (kcal) — drives strain / ความเหนื่อยล้า
        group.enter()
        fetchSamples(.activeEnergyBurned, since: since) { samples in
            let mapped = samples.map { "CAL|\(self.iso($0.0))|\(String(format: "%.1f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            bumpProgress()
            group.leave()
        }

        // SpO2 (percent as 0-1 fraction)
        group.enter()
        fetchSamples(.oxygenSaturation, since: since) { samples in
            let mapped = samples.map { "SPO2|\(self.iso($0.0))|\(String(format: "%.3f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            bumpProgress()
            group.leave()
        }

        // Respiratory Rate (breaths/min)
        group.enter()
        fetchSamples(.respiratoryRate, since: since) { samples in
            let mapped = samples.map { "RR|\(self.iso($0.0))|\(String(format: "%.1f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            bumpProgress()
            group.leave()
        }

        // Sleep (last 36 hrs to cover last night fully)
        let since36h = Calendar.current.date(byAdding: .hour, value: -36, to: Date())!
        group.enter()
        fetchSleep(since: since36h) { samples in
            let mapped = samples.map { s in
                "SLEEP|\(self.iso(s.start))|\(self.iso(s.end))|\(s.stage)"
            }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            bumpProgress()
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
                // Active energy burned during the workout (sum across the session)
                var kcal = ""
                if let estats = w.statistics(for: HKQuantityType(.activeEnergyBurned)),
                   let sum = estats.sumQuantity() {
                    kcal = String(format: "%.0f", sum.doubleValue(for: .kilocalorie()))
                } else if let total = w.totalEnergyBurned {
                    // Fallback for older HealthKit data where statistics() is nil
                    kcal = String(format: "%.0f", total.doubleValue(for: .kilocalorie()))
                }
                let line = "WK|\(type)|\(start)|\(dur)|\(hrAvg)|\(hrMax)|\(kcal)"
                lock.lock(); lines.append(line); lock.unlock()
            }
            bumpProgress()
            group.leave()
        }

        group.notify(queue: .main) { [weak self] in
            guard !lines.isEmpty else {
                self?.syncStatus = "ไม่มี data ใหม่"
                self?.syncProgress = 1.0
                // Brief pause so user can see 100% before banner hides
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                    self?.isSyncing = false
                }
                return
            }
            let payload = lines.joined(separator: "\n")
            self?.api.postSync(payload: payload) { ok in
                DispatchQueue.main.async {
                    let formatter = DateFormatter()
                    formatter.dateFormat = "HH:mm"
                    self?.lastSyncText = "วันนี้ \(formatter.string(from: Date()))"
                    self?.syncStatus = ok ? "✅ \(lines.count) rows" : "❌ ส่งไม่สำเร็จ"
                    self?.syncProgress = 1.0
                    // Brief pause so user can see 100% before banner hides
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                        self?.isSyncing = false
                        if ok { self?.syncCompletedCount += 1 }
                    }
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
            case .heartRate, .restingHeartRate, .respiratoryRate:
                return .count().unitDivided(by: .minute())
            case .heartRateVariabilitySDNN:
                return .secondUnit(with: .milli)
            case .stepCount:
                return .count()
            case .activeEnergyBurned:
                return .kilocalorie()
            case .oxygenSaturation:
                return .percent()
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

    // MARK: - Initial Backfill (first install)

    /// On first install, fetch 5 years of HealthKit history → POST to backend in chunks.
    /// After completion, mark `didBackfill=true` so it never runs again on this device.
    /// Subsequent app opens just call `syncNow()` (incremental 25h).
    func initialBackfillIfNeeded() {
        // Atomic check-and-set on main thread (same pattern as syncNow)
        if Thread.isMainThread {
            _initialBackfillInternal()
        } else {
            DispatchQueue.main.async { self._initialBackfillInternal() }
        }
    }

    private func _initialBackfillInternal() {
        if UserDefaults.standard.bool(forKey: "didBackfill") {
            syncNow()
            return
        }
        if isBackfilling { return }

        isBackfilling = true
        backfillProgress = 0.0
        backfillStatus = "กำลังตั้งค่าครั้งแรก…"

        // 60 chunks × 30 days = 5 years backwards from now
        let chunkDays = 30
        let totalChunks = 60
        let cal = Calendar.current
        let now = Date()
        let chunks: [(Date, Date)] = (0..<totalChunks).map { i in
            let end = cal.date(byAdding: .day, value: -i * chunkDays, to: now)!
            let start = cal.date(byAdding: .day, value: -(i + 1) * chunkDays, to: now)!
            return (start, end)
        }

        processChunksSequentially(chunks: chunks, index: 0)
    }

    private func processChunksSequentially(chunks: [(Date, Date)], index: Int) {
        guard index < chunks.count else {
            // All done
            UserDefaults.standard.set(true, forKey: "didBackfill")
            DispatchQueue.main.async {
                self.backfillProgress = 1.0
                self.backfillStatus = "ตั้งค่าครั้งแรกเสร็จ ✓"
                // Brief pause so user sees 100%, then hide banner
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                    self.isBackfilling = false
                    self.syncCompletedCount += 1  // trigger dashboard refresh
                }
                // Then run normal incremental sync to catch any last-25h samples
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
                    self.syncNow()
                }
            }
            return
        }

        let (start, end) = chunks[index]
        backfillChunk(start: start, end: end) { [weak self] _ in
            guard let self = self else { return }
            DispatchQueue.main.async {
                self.backfillProgress = Double(index + 1) / Double(chunks.count)
            }
            // Recurse — sequential to avoid hammering backend
            self.processChunksSequentially(chunks: chunks, index: index + 1)
        }
    }

    private func backfillChunk(start: Date, end: Date, completion: @escaping (Bool) -> Void) {
        let group = DispatchGroup()
        var lines: [String] = []
        let lock = NSLock()

        // HR
        group.enter()
        fetchSamplesRange(.heartRate, start: start, end: end) { samples in
            let mapped = samples.map { "HR|\(self.iso($0.0))|\(String(format: "%.0f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            group.leave()
        }
        // HRV
        group.enter()
        fetchSamplesRange(.heartRateVariabilitySDNN, start: start, end: end) { samples in
            let mapped = samples.map { "HRV|\(self.iso($0.0))|\(String(format: "%.1f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            group.leave()
        }
        // RHR
        group.enter()
        fetchSamplesRange(.restingHeartRate, start: start, end: end) { samples in
            let mapped = samples.map { "RHR|\(self.iso($0.0))|\(String(format: "%.0f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            group.leave()
        }
        // Steps
        group.enter()
        fetchSamplesRange(.stepCount, start: start, end: end) { samples in
            let mapped = samples.map { "STEPS|\(self.iso($0.0))|\(String(format: "%.0f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            group.leave()
        }
        // Active Energy
        group.enter()
        fetchSamplesRange(.activeEnergyBurned, start: start, end: end) { samples in
            let mapped = samples.map { "CAL|\(self.iso($0.0))|\(String(format: "%.1f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            group.leave()
        }
        // SpO2
        group.enter()
        fetchSamplesRange(.oxygenSaturation, start: start, end: end) { samples in
            let mapped = samples.map { "SPO2|\(self.iso($0.0))|\(String(format: "%.3f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            group.leave()
        }
        // RR
        group.enter()
        fetchSamplesRange(.respiratoryRate, start: start, end: end) { samples in
            let mapped = samples.map { "RR|\(self.iso($0.0))|\(String(format: "%.1f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            group.leave()
        }
        // Sleep
        group.enter()
        fetchSleepRange(start: start, end: end) { samples in
            let mapped = samples.map { "SLEEP|\(self.iso($0.start))|\(self.iso($0.end))|\($0.stage)" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            group.leave()
        }
        // Workouts
        group.enter()
        fetchWorkoutsRange(start: start, end: end) { workouts in
            for w in workouts {
                let type = w.workoutActivityType.name
                let dur = String(format: "%.0f", w.duration / 60)
                let s = self.iso(w.startDate)
                var hrAvg = ""
                var hrMax = ""
                if let stats = w.statistics(for: HKQuantityType(.heartRate)) {
                    if let avg = stats.averageQuantity() {
                        hrAvg = String(format: "%.0f", avg.doubleValue(for: .count().unitDivided(by: .minute())))
                    }
                    if let mx = stats.maximumQuantity() {
                        hrMax = String(format: "%.0f", mx.doubleValue(for: .count().unitDivided(by: .minute())))
                    }
                }
                var kcal = ""
                if let estats = w.statistics(for: HKQuantityType(.activeEnergyBurned)),
                   let sum = estats.sumQuantity() {
                    kcal = String(format: "%.0f", sum.doubleValue(for: .kilocalorie()))
                } else if let total = w.totalEnergyBurned {
                    kcal = String(format: "%.0f", total.doubleValue(for: .kilocalorie()))
                }
                let line = "WK|\(type)|\(s)|\(dur)|\(hrAvg)|\(hrMax)|\(kcal)"
                lock.lock(); lines.append(line); lock.unlock()
            }
            group.leave()
        }

        group.notify(queue: .global()) { [weak self] in
            guard let self = self else { completion(false); return }
            if lines.isEmpty {
                completion(true)
                return
            }
            let payload = lines.joined(separator: "\n")
            self.api.postSync(payload: payload) { ok in
                completion(ok)
            }
        }
    }

    // MARK: - Range fetches (used by backfill)

    private func fetchSamplesRange(
        _ type: HKQuantityTypeIdentifier,
        start: Date,
        end: Date,
        completion: @escaping ([(Date, Double)]) -> Void
    ) {
        let qt = HKQuantityType(type)
        let pred = HKQuery.predicateForSamples(withStart: start, end: end)
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)

        let unit: HKUnit = {
            switch type {
            case .heartRate, .restingHeartRate, .respiratoryRate:
                return .count().unitDivided(by: .minute())
            case .heartRateVariabilitySDNN:
                return .secondUnit(with: .milli)
            case .stepCount:
                return .count()
            case .activeEnergyBurned:
                return .kilocalorie()
            case .oxygenSaturation:
                return .percent()
            default:
                return .count()
            }
        }()

        let query = HKSampleQuery(
            sampleType: qt, predicate: pred, limit: 10000, sortDescriptors: [sort]
        ) { _, results, _ in
            let samples = (results as? [HKQuantitySample])?.map {
                ($0.startDate, $0.quantity.doubleValue(for: unit))
            } ?? []
            completion(samples)
        }
        store.execute(query)
    }

    private func fetchSleepRange(start: Date, end: Date, completion: @escaping ([SleepSample]) -> Void) {
        let qt = HKCategoryType(.sleepAnalysis)
        let pred = HKQuery.predicateForSamples(withStart: start, end: end)
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)

        let query = HKSampleQuery(
            sampleType: qt, predicate: pred, limit: 5000, sortDescriptors: [sort]
        ) { _, results, _ in
            let samples = (results as? [HKCategorySample])?.map { s -> SleepSample in
                SleepSample(start: s.startDate, end: s.endDate, stage: sleepStageName(s.value))
            } ?? []
            completion(samples)
        }
        store.execute(query)
    }

    private func fetchWorkoutsRange(start: Date, end: Date, completion: @escaping ([HKWorkout]) -> Void) {
        let pred = HKQuery.predicateForSamples(withStart: start, end: end)
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)

        let query = HKSampleQuery(
            sampleType: .workoutType(), predicate: pred, limit: 200, sortDescriptors: [sort]
        ) { _, results, _ in
            completion(results as? [HKWorkout] ?? [])
        }
        store.execute(query)
    }

    // Sleep sample: start/end/stage
    struct SleepSample {
        let start: Date
        let end: Date
        let stage: String
    }

    private func fetchSleep(since: Date, completion: @escaping ([SleepSample]) -> Void) {
        let qt = HKCategoryType(.sleepAnalysis)
        let pred = HKQuery.predicateForSamples(withStart: since, end: Date())
        let sort = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)

        let query = HKSampleQuery(
            sampleType: qt, predicate: pred, limit: 2000, sortDescriptors: [sort]
        ) { _, results, _ in
            let samples = (results as? [HKCategorySample])?.map { s -> SleepSample in
                SleepSample(start: s.startDate, end: s.endDate, stage: sleepStageName(s.value))
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

// Map sleep category value to HealthKit string name
private func sleepStageName(_ value: Int) -> String {
    switch value {
    case HKCategoryValueSleepAnalysis.inBed.rawValue:
        return "HKCategoryValueSleepAnalysisInBed"
    case HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue:
        return "HKCategoryValueSleepAnalysisAsleepUnspecified"
    case HKCategoryValueSleepAnalysis.awake.rawValue:
        return "HKCategoryValueSleepAnalysisAwake"
    case HKCategoryValueSleepAnalysis.asleepCore.rawValue:
        return "HKCategoryValueSleepAnalysisAsleepCore"
    case HKCategoryValueSleepAnalysis.asleepDeep.rawValue:
        return "HKCategoryValueSleepAnalysisAsleepDeep"
    case HKCategoryValueSleepAnalysis.asleepREM.rawValue:
        return "HKCategoryValueSleepAnalysisAsleepREM"
    default:
        return "HKCategoryValueSleepAnalysisAsleepUnspecified"
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
