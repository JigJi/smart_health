import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'สุขภาพดี',
  description: 'ผู้ช่วยสุขภาพส่วนตัว',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="th">
      <body className="bg-bg text-primary antialiased">{children}</body>
    </html>
  );
}
