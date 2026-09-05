import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

// Self-hosted via next/font instead of a render-blocking Google stylesheet link.
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "RazorShield AI — Autonomous Merchant Risk Inspector",
  description:
    "Autonomous multi-agent merchant onboarding risk analysis for payment gateways: policy compliance, prohibited catalog detection, and digital footprint scoring.",
  keywords: [
    "merchant risk",
    "payment gateway",
    "fraud detection",
    "KYB",
    "onboarding risk",
    "AI risk analysis",
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="antialiased font-sans bg-canvas text-ink">{children}</body>
    </html>
  );
}
