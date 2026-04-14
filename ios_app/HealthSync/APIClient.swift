//
//  APIClient.swift
//  HealthSync
//
//  Created by Jirawat Sangthong on 12/4/2569 BE.
//

import Foundation

class APIClient {
    // Production: Tailscale Funnel public HTTPS URL → Windows server backend
    // (LAN dev fallback: http://192.168.1.38:8401)
    static let baseURL = "https://voizely-backend.tailb8d083.ts.net:10000"

    /// UUID per install — generated once on first launch, persisted in UserDefaults.
    /// Ensures each user's data stays isolated on the server (multi-user support).
    static func userId() -> String {
        if let existing = UserDefaults.standard.string(forKey: "userId") {
            return existing
        }
        let new = UUID().uuidString
        UserDefaults.standard.set(new, forKey: "userId")
        return new
    }

    func postSync(payload: String, completion: @escaping (Bool) -> Void) {
        guard let url = URL(string: "\(Self.baseURL)/sync/shortcut") else {
            completion(false)
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("text/plain; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.setValue(Self.userId(), forHTTPHeaderField: "X-User-Id")
        request.httpBody = payload.data(using: .utf8)
        request.timeoutInterval = 30

        URLSession.shared.dataTask(with: request) { data, response, error in
            if let http = response as? HTTPURLResponse {
                completion(http.statusCode == 200)
            } else {
                completion(false)
            }
        }.resume()
    }
}
