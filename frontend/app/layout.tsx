import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'smart_health',
  description: 'Apple Health recovery & strain dashboard',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
