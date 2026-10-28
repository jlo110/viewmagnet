import Navbar from "@/components/Navbar";
import Comparison from "@/components/sections/Comparison";
import CTA from "@/components/sections/CTA";
import Differentiator from "@/components/sections/Differentiator";
import FAQ from "@/components/sections/FAQ";
import Features from "@/components/sections/Features";
import Footer from "@/components/sections/Footer";
import Hero from "@/components/sections/Hero";
import HowItWorks from "@/components/sections/HowItWorks";
import ModelAccuracy from "@/components/sections/ModelAccuracy";
import Pricing from "@/components/sections/Pricing";
import SocialProof from "@/components/sections/SocialProof";
import { SEOHead, StructuredData } from "@/components/seo";

export default function Home() {
  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      <SEOHead
        title="Predict, create, publish — the full YouTube workflow"
        description="The only platform that predicts a video's performance before you film it, then helps you script, edit, and publish the winning version. One app for the whole loop — no tool-switching."
        canonicalUrl="/"
        keywords="YouTube growth tool, video analyzer, script writer, video editor, AI for creators, YouTube prediction, viral framework, hook generator, thumbnail tester"
        markdownUrl="/index.md"
      />
      <StructuredData type="organization" />
      <StructuredData type="website" />
      {/* SoftwareApplication schema — gives Google + AI search
          engines the rich-card metadata for a SaaS product
          (category, free tier, OS). */}
      <StructuredData
        type="softwareApplication"
        name="ViewMagnet"
        description="Predict, create, and publish YouTube videos in one app. ML-driven analyzer, script writer with four viral frameworks, full studio editor, and distribution hub."
        applicationCategory="MultimediaApplication"
        operatingSystem="Web Browser"
        offers={[
          {
            price: 0,
            priceCurrency: "USD",
          },
        ]}
      />
      <Navbar />
      <main>
        <Hero />
        <SocialProof />
        <Features />
        <HowItWorks />
        <Differentiator />
        <ModelAccuracy />
        <Pricing />
        <Comparison />
        <FAQ />
        <CTA />
      </main>
      <Footer />
    </div>
  );
}
