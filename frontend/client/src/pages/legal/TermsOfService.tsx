import { Link } from "wouter";
import { ArrowLeft, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SEOHead, StructuredData } from "@/components/seo";

export default function TermsOfService() {
  return (
    <>
    <SEOHead
      title="Terms of Service"
      description="The terms under which you use ViewMagnet's tools, content, and APIs. Plain-English where possible, legalese where required."
      canonicalUrl="/terms"
    />
    <StructuredData
      type="breadcrumb"
      items={[
        { name: "Home", url: "/" },
        { name: "Terms of Service", url: "/terms" },
      ]}
    />
    <div className="min-h-screen bg-gradient-to-b from-deep-charcoal to-gunmetal">
      <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-lg">
        <div className="container mx-auto px-4 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-glow to-amber-glow flex items-center justify-center">
              <Zap className="w-4 h-4 text-deep-charcoal" strokeWidth={2.5} />
            </div>
            <span className="text-lg font-bold">
              View<span className="text-cyan-glow">Magnet</span>
            </span>
          </Link>
          <Button variant="ghost" size="sm" asChild>
            <Link href="/">
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Home
            </Link>
          </Button>
        </div>
      </header>

      <main className="container mx-auto px-4 py-12 max-w-4xl">
        <h1 className="text-3xl font-bold mb-2">Terms of Service</h1>
        <p className="text-muted-foreground mb-8">Last updated: February 21, 2026</p>

        <div className="prose prose-invert prose-cyan max-w-none space-y-8">
          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">1. Acceptance of Terms</h2>
            <p className="text-muted-foreground leading-relaxed">
              By accessing or using ViewMagnet ("the Service"), you agree to be bound by these Terms of Service. 
              If you do not agree to these terms, please do not use the Service. We reserve the right to 
              modify these terms at any time, and your continued use of the Service constitutes acceptance 
              of any modifications.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">2. Description of Service</h2>
            <p className="text-muted-foreground leading-relaxed">
              ViewMagnet provides YouTube video analysis, performance prediction, and optimization tools. 
              Our services include but are not limited to: video performance scoring, title and thumbnail 
              analysis, competitor research, trend analysis, and AI-powered content recommendations.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">3. User Accounts</h2>
            <p className="text-muted-foreground leading-relaxed mb-4">
              To access certain features of the Service, you must create an account. You agree to:
            </p>
            <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-4">
              <li>Provide accurate, current, and complete information during registration</li>
              <li>Maintain the security of your password and account</li>
              <li>Accept responsibility for all activities that occur under your account</li>
              <li>Notify us immediately of any unauthorized use of your account</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">4. YouTube API Services</h2>
            <p className="text-muted-foreground leading-relaxed mb-4">
              ViewMagnet uses YouTube API Services. By using our Service, you also agree to be bound by 
              YouTube's Terms of Service (<a href="https://www.youtube.com/t/terms" className="text-cyan-glow hover:underline" target="_blank" rel="noopener noreferrer">https://www.youtube.com/t/terms</a>) and 
              Google's Privacy Policy (<a href="https://policies.google.com/privacy" className="text-cyan-glow hover:underline" target="_blank" rel="noopener noreferrer">https://policies.google.com/privacy</a>).
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">5. Subscription and Payments</h2>
            <p className="text-muted-foreground leading-relaxed mb-4">
              Some features require a paid subscription. By subscribing, you agree to:
            </p>
            <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-4">
              <li>Pay all fees associated with your chosen plan</li>
              <li>Automatic renewal unless cancelled before the renewal date</li>
              <li>No refunds for partial subscription periods, except as required by law</li>
              <li>Price changes will be communicated 30 days in advance</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">6. Acceptable Use</h2>
            <p className="text-muted-foreground leading-relaxed mb-4">
              You agree not to:
            </p>
            <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-4">
              <li>Use the Service for any unlawful purpose</li>
              <li>Attempt to gain unauthorized access to any part of the Service</li>
              <li>Use automated scripts to access the Service without permission</li>
              <li>Interfere with or disrupt the integrity of the Service</li>
              <li>Resell or redistribute the Service without authorization</li>
              <li>Use the Service to violate YouTube's Terms of Service or Community Guidelines</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">7. Intellectual Property</h2>
            <p className="text-muted-foreground leading-relaxed">
              The Service and its original content, features, and functionality are owned by ViewMagnet 
              and are protected by international copyright, trademark, and other intellectual property laws. 
              You retain ownership of your content, but grant us a license to use it as necessary to 
              provide the Service.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">8. Disclaimer of Warranties</h2>
            <p className="text-muted-foreground leading-relaxed">
              The Service is provided "as is" without warranties of any kind. We do not guarantee that 
              predictions or recommendations will result in increased views, subscribers, or engagement. 
              YouTube's algorithms and policies may change at any time, and results may vary.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">9. Limitation of Liability</h2>
            <p className="text-muted-foreground leading-relaxed">
              To the maximum extent permitted by law, ViewMagnet shall not be liable for any indirect, 
              incidental, special, consequential, or punitive damages, including loss of profits, data, 
              or other intangible losses resulting from your use of the Service.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">10. Termination</h2>
            <p className="text-muted-foreground leading-relaxed">
              We reserve the right to terminate or suspend your account and access to the Service at our 
              sole discretion, without notice, for conduct that we believe violates these Terms or is 
              harmful to other users, us, or third parties.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">11. Changes to Terms</h2>
            <p className="text-muted-foreground leading-relaxed">
              We may modify these Terms at any time. We will notify you of significant changes by email 
              or through the Service. Your continued use of the Service after changes become effective 
              constitutes acceptance of the revised Terms.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">12. Contact Information</h2>
            <p className="text-muted-foreground leading-relaxed">
              If you have questions about these Terms, please contact us at{" "}
              <a href="mailto:legal@viewmagnet.com" className="text-cyan-glow hover:underline">
                legal@viewmagnet.com
              </a>
            </p>
          </section>
        </div>

        <div className="mt-12 pt-8 border-t border-border/50 flex flex-wrap gap-4 text-sm text-muted-foreground">
          <Link href="/privacy" className="text-cyan-glow hover:underline">
            Privacy Policy
          </Link>
          <span>•</span>
          <Link href="/" className="hover:text-foreground">
            Home
          </Link>
          <span>•</span>
          <Link href="/login" className="hover:text-foreground">
            Sign In
          </Link>
        </div>
      </main>
    </div>
    </>
  );
}
