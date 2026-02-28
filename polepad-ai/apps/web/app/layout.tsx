import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'PolePad AI — Infrastructure Verification',
  description: 'Crowd-powered utility pole inspection system',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
