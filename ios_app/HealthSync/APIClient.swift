import Foundation

class APIClient {
    // TODO: เปลี่ยนเป็น URL จริงของ backend
    // ตอน dev ใช้ Tailscale IP หรือ ngrok
    static let baseURL = "http://100.105.182.33:8401"

    func postSync(payload: String, completion: @escaping (Bool) -> Void) {
        guard let url = URL(string: "\(Self.baseURL)/sync/shortcut") else {
            completion(false)
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("text/plain; charset=utf-8", forHTTPHeaderField: "Content-Type")
        // TODO: ใส่ LINE user ID เพื่อแยก user
        request.setValue("default", forHTTPHeaderField: "X-User-Id")
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
