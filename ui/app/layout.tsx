import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { Providers } from "@/components/providers";
import { readRuntimeConfig } from "@/lib/read-runtime-config";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Customer signup",
  description: "Register as a customer, with an assistant to explain any problem.",
};

// The API origin is read from the server environment on every request, so one build serves
// every environment.
export const dynamic = "force-dynamic";

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const config = readRuntimeConfig();
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <Providers config={config}>{children}</Providers>
      </body>
    </html>
  );
}
