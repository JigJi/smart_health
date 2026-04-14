import SwiftUI
import WebKit

struct WebViewContainer: UIViewRepresentable {
    let url: URL
    var reloadTrigger: Int = 0

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.allowsBackForwardNavigationGestures = true
        webView.isOpaque = false
        webView.underPageBackgroundColor = UIColor(red: 0.078, green: 0.078, blue: 0.078, alpha: 1)
        webView.scrollView.backgroundColor = UIColor(red: 0.078, green: 0.078, blue: 0.078, alpha: 1)
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        if webView.url == nil {
            webView.load(URLRequest(url: url))
        } else if context.coordinator.lastReloadTrigger != reloadTrigger {
            context.coordinator.lastReloadTrigger = reloadTrigger
            // Silent refetch — keep DOM, re-fetch data only (Bevel-style)
            webView.evaluateJavaScript("window.__refreshData && window.__refreshData()")
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    class Coordinator {
        var lastReloadTrigger: Int = 0
    }
}
