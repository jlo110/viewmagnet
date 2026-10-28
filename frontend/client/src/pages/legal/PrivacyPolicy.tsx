import { Link } from "wouter";
import { ArrowLeft, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SEOHead, StructuredData } from "@/components/seo";

export default function PrivacyPolicy() {
  return (
    <>
    <SEOHead
      title="Privacy Policy"
      description="How ViewMagnet collects, uses, stores, and protects your data. GDPR and CCPA compliant."
      canonicalUrl="/privacy"
    />
    <StructuredData
      type="breadcrumb"
      items={[
        { name: "Home", url: "/" },
        { name: "Privacy Policy", url: "/privacy" },
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
        <h1 className="text-3xl font-bold mb-2">Privacy Policy</h1>
        <p className="text-muted-foreground mb-8">Last updated: February 21, 2026</p>

        <div className="prose prose-invert prose-cyan max-w-none space-y-8">
          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">1. Introduction</h2>
            <p className="text-muted-foreground leading-relaxed">
              ViewMagnet ("we," "our," or "us") is committed to protecting your privacy. This Privacy Policy 
              explains how we collect, use, disclose, and safeguard your information when you use our 
              video analysis and optimization service.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">2. Information We Collect</h2>
            
            <h3 className="text-lg font-medium text-foreground mt-6 mb-3">2.1 Information You Provide</h3>
            <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-4">
              <li>Account information: email address, name, and password</li>
              <li>Profile information: avatar, preferences, and settings</li>
              <li>Payment information: processed securely through Stripe</li>
              <li>Communication: messages you send to our support team</li>
            </ul>

            <h3 className="text-lg font-medium text-foreground mt-6 mb-3">2.2 Information from YouTube</h3>
            <p className="text-muted-foreground leading-relaxed mb-4">
              When you connect your YouTube channel, we access:
            </p>
            <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-4">
              <li>Channel information: name, subscriber count, and channel ID</li>
              <li>Video metadata: titles, descriptions, thumbnails, and tags</li>
              <li>Performance metrics: views, likes, comments, and engagement data</li>
              <li>Analytics data: traffic sources, audience demographics (if authorized)</li>
            </ul>

            <h3 className="text-lg font-medium text-foreground mt-6 mb-3">2.3 Automatically Collected Information</h3>
            <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-4">
              <li>Device information: browser type, operating system, device type</li>
              <li>Usage data: features used, pages visited, actions taken</li>
              <li>Log data: IP address, access times, referring URLs</li>
              <li>Cookies and similar technologies for session management</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">3. How We Use Your Information</h2>
            <p className="text-muted-foreground leading-relaxed mb-4">
              We use collected information to:
            </p>
            <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-4">
              <li>Provide, maintain, and improve our services</li>
              <li>Analyze your videos and generate performance predictions</li>
              <li>Compare your content against industry benchmarks</li>
              <li>Generate personalized recommendations and insights</li>
              <li>Process payments and manage subscriptions</li>
              <li>Send service updates, security alerts, and support messages</li>
              <li>Detect and prevent fraud, abuse, and security issues</li>
              <li>Comply with legal obligations</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">4. YouTube API Services</h2>
            <p className="text-muted-foreground leading-relaxed mb-4">
              ViewMagnet uses YouTube API Services. Our use and transfer of information received from 
              Google APIs adheres to the{" "}
              <a 
                href="https://developers.google.com/terms/api-services-user-data-policy" 
                className="text-cyan-glow hover:underline" 
                target="_blank" 
                rel="noopener noreferrer"
              >
                Google API Services User Data Policy
              </a>
              , including the Limited Use requirements.
            </p>
            <p className="text-muted-foreground leading-relaxed mb-4">
              You can revoke our access to your YouTube data at any time through:
            </p>
            <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-4">
              <li>Your ViewMagnet account settings</li>
              <li>
                Google's security settings at{" "}
                <a 
                  href="https://myaccount.google.com/permissions" 
                  className="text-cyan-glow hover:underline" 
                  target="_blank" 
                  rel="noopener noreferrer"
                >
                  https://myaccount.google.com/permissions
                </a>
              </li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">5. Data Sharing and Disclosure</h2>
            <p className="text-muted-foreground leading-relaxed mb-4">
              We do not sell your personal information. We may share information with:
            </p>
            <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-4">
              <li><strong className="text-foreground">Service providers:</strong> Companies that help us operate (hosting, payment processing, analytics)</li>
              <li><strong className="text-foreground">Legal requirements:</strong> When required by law or to protect our rights</li>
              <li><strong className="text-foreground">Business transfers:</strong> In connection with a merger, acquisition, or sale of assets</li>
              <li><strong className="text-foreground">With your consent:</strong> When you explicitly authorize sharing</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">6. Data Retention</h2>
            <p className="text-muted-foreground leading-relaxed">
              We retain your information for as long as your account is active or as needed to provide 
              services. You can request deletion of your account and associated data at any time. 
              Some information may be retained as required by law or for legitimate business purposes.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">7. Data Security</h2>
            <p className="text-muted-foreground leading-relaxed">
              We implement industry-standard security measures to protect your information, including:
            </p>
            <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-4 mt-4">
              <li>Encryption of data in transit (TLS/SSL) and at rest</li>
              <li>Secure password hashing using bcrypt</li>
              <li>Regular security audits and monitoring</li>
              <li>Access controls and authentication requirements</li>
              <li>Secure hosting on enterprise-grade infrastructure</li>
            </ul>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">8. Your Rights and Choices</h2>
            <p className="text-muted-foreground leading-relaxed mb-4">
              Depending on your location, you may have the right to:
            </p>
            <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-4">
              <li><strong className="text-foreground">Access:</strong> Request a copy of your personal data</li>
              <li><strong className="text-foreground">Correction:</strong> Update or correct inaccurate information</li>
              <li><strong className="text-foreground">Deletion:</strong> Request deletion of your personal data</li>
              <li><strong className="text-foreground">Portability:</strong> Receive your data in a portable format</li>
              <li><strong className="text-foreground">Objection:</strong> Object to certain processing activities</li>
              <li><strong className="text-foreground">Withdrawal:</strong> Withdraw consent where processing is based on consent</li>
            </ul>
            <p className="text-muted-foreground leading-relaxed mt-4">
              To exercise these rights, contact us at{" "}
              <a href="mailto:privacy@viewmagnet.com" className="text-cyan-glow hover:underline">
                privacy@viewmagnet.com
              </a>
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">9. Cookies and Tracking</h2>
            <p className="text-muted-foreground leading-relaxed mb-4">
              We use cookies and similar technologies for:
            </p>
            <ul className="list-disc list-inside text-muted-foreground space-y-2 ml-4">
              <li><strong className="text-foreground">Essential cookies:</strong> Required for the Service to function</li>
              <li><strong className="text-foreground">Authentication:</strong> To keep you signed in</li>
              <li><strong className="text-foreground">Preferences:</strong> To remember your settings</li>
              <li><strong className="text-foreground">Analytics:</strong> To understand how you use our Service</li>
            </ul>
            <p className="text-muted-foreground leading-relaxed mt-4">
              You can control cookies through your browser settings, but some features may not work properly 
              if cookies are disabled.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">10. International Data Transfers</h2>
            <p className="text-muted-foreground leading-relaxed">
              Your information may be transferred to and processed in countries other than your own. 
              We ensure appropriate safeguards are in place to protect your information in accordance 
              with this Privacy Policy and applicable law.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">11. Children's Privacy</h2>
            <p className="text-muted-foreground leading-relaxed">
              Our Service is not intended for children under 13 (or the applicable age of consent in your 
              jurisdiction). We do not knowingly collect personal information from children. If you believe 
              we have collected information from a child, please contact us immediately.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">12. Changes to This Policy</h2>
            <p className="text-muted-foreground leading-relaxed">
              We may update this Privacy Policy from time to time. We will notify you of significant 
              changes by email or through the Service. Your continued use of the Service after changes 
              become effective constitutes acceptance of the revised Privacy Policy.
            </p>
          </section>

          <section>
            <h2 className="text-xl font-semibold text-foreground mb-4">13. Contact Us</h2>
            <p className="text-muted-foreground leading-relaxed">
              If you have questions about this Privacy Policy or our data practices, please contact us at:
            </p>
            <div className="mt-4 p-4 bg-secondary/30 rounded-lg">
              <p className="text-foreground font-medium">ViewMagnet</p>
              <p className="text-muted-foreground">
                Email:{" "}
                <a href="mailto:privacy@viewmagnet.com" className="text-cyan-glow hover:underline">
                  privacy@viewmagnet.com
                </a>
              </p>
            </div>
          </section>
        </div>

        <div className="mt-12 pt-8 border-t border-border/50 flex flex-wrap gap-4 text-sm text-muted-foreground">
          <Link href="/terms" className="text-cyan-glow hover:underline">
            Terms of Service
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
