import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "RazorShield AI — Autonomous Merchant Risk Inspector",
  description:
    "Enterprise-grade autonomous multi-agent merchant onboarding risk analysis platform for payment gateways. Powered by RazorShield AI.",
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
    <html lang="en" className={`dark ${inter.variable}`}>
      <head>
        {/* JetBrains Mono for monospace/terminal surfaces */}
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="antialiased font-sans">{children}</body>
    </html>
  );
}
