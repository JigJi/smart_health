import './globals.css';
import type { Metadata, Viewport } from 'next';

export const metadata: Metadata = {
  title: 'livvv',
  description: 'ผู้ช่วยสุขภาพส่วนตัว',
};

// Disable double-tap-to-zoom → kills 300ms tap delay on iOS WebView
export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="th">
      <body className="bg-bg text-primary antialiased">{children}</body>
    </html>
  );
}
