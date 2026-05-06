import "./globals.css";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "FireGuard",
  description: "Wildfire evacuation orchestration agent.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
