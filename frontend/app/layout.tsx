import type { Metadata } from 'next';
import { Instrument_Serif, Manrope } from 'next/font/google';
import { AuthProvider } from '@/lib/auth-context';
import './globals.css';

const instrumentSerif = Instrument_Serif({
  subsets: ['latin'],
  weight: ['400'],
  style: ['normal', 'italic'],
  variable: '--font-instrument-serif',
});

const manrope = Manrope({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700', '800'],
  variable: '--font-manrope',
});

export const metadata: Metadata = {
  title: 'Doc Assist',
  description: 'HR & SOPs workspace',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${instrumentSerif.variable} ${manrope.variable}`}>
      <body className="bg-[#0B0F08] font-sans text-[#EDF2E6] antialiased">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
