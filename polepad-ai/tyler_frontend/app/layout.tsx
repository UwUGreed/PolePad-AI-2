import "./globals.css";
import Header from "@/components/Header";

export const metadata = {
  title: "PalpadAI",
  description: "Utility portal demo",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-gray-900">
        <Header />
        {children}
      </body>
    </html>
  );
}