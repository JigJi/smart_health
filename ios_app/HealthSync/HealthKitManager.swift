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
        // Prevent concurrent syncs
        if isSyncing { return }
        DispatchQueue.main.async {
            self.isSyncing = true
            self.syncProgress = 0.0
            self.syncStatus = "กำลัง sync..."
        }

        // 10 phases: 9 fetches (HR/HRV/RHR/Steps/Cal/SpO2/RR/Sleep/Workouts) + 1 post
        let phaseStep = 1.0 / 10.0

        let since = Calendar.current.date(byAdding: .hour, value: -25, to: Date())!
        let group = DispatchGroup()

        var lines: [String] = []
        let lock = NSLock()

        // Heart Rate
        group.enter()
        fetchSamples(.heartRate, since: since) { samples in
            let mapped = samples.map { "HR|\(self.iso($0.0))|\(String(format: "%.0f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            DispatchQueue.main.async {
                self.todayHRCount = samples.count
                self.syncProgress += phaseStep
            }
            group.leave()
        }

        // HRV
        group.enter()
        fetchSamples(.heartRateVariabilitySDNN, since: since) { samples in
            let mapped = samples.map { "HRV|\(self.iso($0.0))|\(String(format: "%.1f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            DispatchQueue.main.async { self.syncProgress += phaseStep }
            group.leave()
        }

        // Resting HR (last 7 days for more data)
        let since7d = Calendar.current.date(byAdding: .day, value: -7, to: Date())!
        group.enter()
        fetchSamples(.restingHeartRate, since: since7d) { samples in
            let mapped = samples.map { "RHR|\(self.iso($0.0))|\(String(format: "%.0f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            DispatchQueue.main.async { self.syncProgress += phaseStep }
            group.leave()
        }

        // Steps
        group.enter()
        fetchSamples(.stepCount, since: since) { samples in
            let mapped = samples.map { "STEPS|\(self.iso($0.0))|\(String(format: "%.0f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            DispatchQueue.main.async { self.syncProgress += phaseStep }
            group.leave()
        }

        // Active Energy (kcal) — drives strain / ความเหนื่อยล้า
        group.enter()
        fetchSamples(.activeEnergyBurned, since: since) { samples in
            let mapped = samples.map { "CAL|\(self.iso($0.0))|\(String(format: "%.1f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            DispatchQueue.main.async { self.syncProgress += phaseStep }
            group.leave()
        }

        // SpO2 (percent as 0-1 fraction)
        group.enter()
        fetchSamples(.oxygenSaturation, since: since) { samples in
            let mapped = samples.map { "SPO2|\(self.iso($0.0))|\(String(format: "%.3f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            DispatchQueue.main.async { self.syncProgress += phaseStep }
            group.leave()
        }

        // Respiratory Rate (breaths/min)
        group.enter()
        fetchSamples(.respiratoryRate, since: since) { samples in
            let mapped = samples.map { "RR|\(self.iso($0.0))|\(String(format: "%.1f", $0.1))" }
            lock.lock(); lines.append(contentsOf: mapped); lock.unlock()
            DispatchQueue.main.async { self.syncProgress += phaseStep }
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
            DispatchQueue.main.async { self.syncProgress += phaseStep }
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
            DispatchQueue.main.async { self.syncProgress += phaseStep }
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
