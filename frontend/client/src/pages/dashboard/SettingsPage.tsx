/*
 * Settings: Account, channel, billing, integrations, referrals
 * Design: Signal Flow dark theme
 */
import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Progress } from "@/components/ui/progress";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  User,
  CreditCard,
  Link2,
  Shield,
  Youtube,
  Chrome,
  Zap,
  CheckCircle2,
  ExternalLink,
  Gift,
  Copy,
  Users,
  Sparkles,
  Twitter,
  Linkedin,
  MessageCircle,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import {
  getReferralStats,
  getSubscription,
  openBillingPortal,
  createCheckout,
  deleteAccount,
  logout,
  type ReferralStats,
  type SubscriptionInfo,
} from "@/lib/api";
import { Trash2, AlertTriangle } from "lucide-react";

export default function SettingsPage() {
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleting, setDeleting] = useState(false);

  const handleDeleteAccount = async () => {
    setDeleting(true);
    try {
      await deleteAccount(deletePassword || undefined);
      toast.success("Your account has been deleted.");
      logout();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Couldn't delete your account. Please try again.");
      setDeleting(false);
    }
  };

  const [referralStats, setReferralStats] = useState<ReferralStats | null>(null);
  const [referralLoading, setReferralLoading] = useState(true);
  const [subscription, setSubscription] = useState<SubscriptionInfo | null>(null);
  const [subscriptionLoading, setSubscriptionLoading] = useState(true);
  const [billingActionLoading, setBillingActionLoading] = useState(false);

  useEffect(() => {
    loadReferralStats();
    loadSubscription();
  }, []);

  const loadSubscription = async () => {
    try {
      const sub = await getSubscription();
      setSubscription(sub);
    } catch (error) {
      console.error("Failed to load subscription:", error);
    } finally {
      setSubscriptionLoading(false);
    }
  };

  const handleManageBilling = async () => {
    setBillingActionLoading(true);
    try {
      const url = await openBillingPortal();
      window.location.href = url;
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status;
      toast.error(
        status === 400
          ? "No billing account yet — subscribe to a plan first."
          : status === 503
            ? "Billing isn't available just yet."
            : "Couldn't open the billing portal. Please try again.",
      );
      setBillingActionLoading(false);
    }
  };

  const handleUpgrade = async (plan: string) => {
    setBillingActionLoading(true);
    try {
      const url = await createCheckout(plan);
      window.location.href = url;
    } catch {
      toast.error("Couldn't start checkout. Please try again.");
      setBillingActionLoading(false);
    }
  };

  const loadReferralStats = async () => {
    try {
      const stats = await getReferralStats();
      setReferralStats(stats);
    } catch (error) {
      console.error("Failed to load referral stats:", error);
    } finally {
      setReferralLoading(false);
    }
  };

  const copyReferralLink = () => {
    if (referralStats?.referral_link) {
      navigator.clipboard.writeText(referralStats.referral_link);
      toast.success("Referral link copied to clipboard!");
    }
  };

  const shareOnTwitter = () => {
    if (!referralStats?.referral_link) return;
    const text = encodeURIComponent("I've been using ViewMagnet to optimize my YouTube videos and it's amazing! Try it out:");
    const url = encodeURIComponent(referralStats.referral_link);
    window.open(`https://twitter.com/intent/tweet?text=${text}&url=${url}`, '_blank');
  };

  const shareOnLinkedIn = () => {
    if (!referralStats?.referral_link) return;
    const url = encodeURIComponent(referralStats.referral_link);
    window.open(`https://www.linkedin.com/sharing/share-offsite/?url=${url}`, '_blank');
  };

  const shareOnWhatsApp = () => {
    if (!referralStats?.referral_link) return;
    const text = encodeURIComponent(`Check out ViewMagnet for YouTube optimization! ${referralStats.referral_link}`);
    window.open(`https://wa.me/?text=${text}`, '_blank');
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold font-[var(--font-display)] tracking-tight">
          Settings
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Manage your account, billing, and integrations.
        </p>
      </div>

      <Tabs defaultValue="account" className="space-y-6">
        <TabsList className="bg-secondary/50">
          <TabsTrigger value="account" className="gap-1.5">
            <User className="w-3.5 h-3.5" />
            Account
          </TabsTrigger>
          <TabsTrigger value="billing" className="gap-1.5">
            <CreditCard className="w-3.5 h-3.5" />
            Billing
          </TabsTrigger>
          <TabsTrigger value="referrals" className="gap-1.5">
            <Gift className="w-3.5 h-3.5" />
            Referrals
          </TabsTrigger>
          <TabsTrigger value="integrations" className="gap-1.5">
            <Link2 className="w-3.5 h-3.5" />
            Integrations
          </TabsTrigger>
        </TabsList>

        {/* Account */}
        <TabsContent value="account" className="space-y-6">
          <Card className="bg-card border-border/50">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold">Profile</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-4">
                <Avatar className="w-16 h-16">
                  <AvatarFallback className="bg-cyan-glow/20 text-cyan-glow text-lg font-bold">
                    JD
                  </AvatarFallback>
                </Avatar>
                <div>
                  <p className="text-sm font-semibold text-foreground">John Doe</p>
                  <p className="text-xs text-muted-foreground">john@example.com</p>
                  <Button variant="ghost" size="sm" className="text-xs text-cyan-glow mt-1 h-6 px-0">
                    Change avatar
                  </Button>
                </div>
              </div>
              <Separator className="bg-border/30" />
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Name</label>
                  <Input defaultValue="John Doe" className="bg-secondary/50 border-border/50" />
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Email</label>
                  <Input defaultValue="john@example.com" className="bg-secondary/50 border-border/50" />
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Niche</label>
                  <Select defaultValue="technology">
                    <SelectTrigger className="bg-secondary/50 border-border/50">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="technology">Technology</SelectItem>
                      <SelectItem value="gaming">Gaming</SelectItem>
                      <SelectItem value="education">Education</SelectItem>
                      <SelectItem value="entertainment">Entertainment</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Timezone</label>
                  <Select defaultValue="est">
                    <SelectTrigger className="bg-secondary/50 border-border/50">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="est">Eastern (EST)</SelectItem>
                      <SelectItem value="pst">Pacific (PST)</SelectItem>
                      <SelectItem value="utc">UTC</SelectItem>
                      <SelectItem value="gmt">GMT</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <Button className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold">
                Save Changes
              </Button>
            </CardContent>
          </Card>

          <Card className="bg-card border-border/50">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold flex items-center gap-2">
                <Shield className="w-4 h-4 text-muted-foreground" />
                Preferences
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {[
                { name: "Email notifications", desc: "Receive alerts via email", enabled: true },
                { name: "Weekly digest", desc: "Summary of channel performance", enabled: false },
                { name: "Dark mode", desc: "Use dark theme (recommended)", enabled: true },
                { name: "Beta features", desc: "Try new features before release", enabled: false },
              ].map((pref) => (
                <div key={pref.name} className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-foreground">{pref.name}</p>
                    <p className="text-[10px] text-muted-foreground">{pref.desc}</p>
                  </div>
                  <Switch defaultChecked={pref.enabled} />
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Danger Zone — permanent account deletion (GDPR right to erasure) */}
          <Card className="bg-card border-rose-500/30">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold flex items-center gap-2 text-rose-400">
                <AlertTriangle className="w-4 h-4" />
                Danger Zone
              </CardTitle>
              <CardDescription>
                Permanently delete your account and all associated data. This cannot be undone.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!deleteOpen ? (
                <Button
                  variant="outline"
                  className="border-rose-500/40 text-rose-400 hover:bg-rose-500/10 hover:text-rose-300"
                  onClick={() => setDeleteOpen(true)}
                >
                  <Trash2 className="w-4 h-4 mr-2" />
                  Delete account
                </Button>
              ) : (
                <div className="space-y-3 rounded-lg border border-rose-500/30 bg-rose-500/5 p-4">
                  <p className="text-sm text-foreground">
                    This will permanently erase your account, projects, renders, and tokens. Enter
                    your password to confirm.
                  </p>
                  <Input
                    type="password"
                    placeholder="Your password"
                    value={deletePassword}
                    onChange={(e) => setDeletePassword(e.target.value)}
                    className="bg-secondary/50 border-border/50 max-w-sm"
                    autoComplete="current-password"
                  />
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      className="border-rose-500/50 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20"
                      onClick={handleDeleteAccount}
                      disabled={deleting}
                    >
                      {deleting ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        "Yes, delete my account"
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => {
                        setDeleteOpen(false);
                        setDeletePassword("");
                      }}
                      disabled={deleting}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Billing */}
        <TabsContent value="billing" className="space-y-6">
          <Card className="bg-card border-border/50">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold">Current Plan</CardTitle>
            </CardHeader>
            <CardContent>
              {subscriptionLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-5 h-5 animate-spin text-cyan-glow" />
                </div>
              ) : subscription ? (
                <>
                  <div className="flex items-center justify-between p-4 rounded-lg bg-cyan-glow/5 border border-cyan-glow/20">
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-lg font-bold font-[var(--font-display)] text-foreground">
                          {subscription.plan_display} Plan
                        </h3>
                        {subscription.status && (
                          <Badge className="bg-cyan-glow/20 text-cyan-glow border-cyan-glow/30 text-[10px] capitalize">
                            {subscription.cancel_at_period_end
                              ? "Cancels at period end"
                              : subscription.status}
                          </Badge>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground mt-1">
                        {subscription.price_cents > 0
                          ? `$${(subscription.price_cents / 100).toFixed(0)}/month`
                          : "Free plan"}
                        {subscription.expires_at &&
                          ` • ${subscription.cancel_at_period_end ? "Ends" : "Renews"} ${new Date(
                            subscription.expires_at,
                          ).toLocaleDateString()}`}
                      </p>
                    </div>
                    {subscription.has_stripe_customer ? (
                      <Button
                        variant="outline"
                        className="border-border/50"
                        onClick={handleManageBilling}
                        disabled={billingActionLoading}
                      >
                        {billingActionLoading ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          "Manage Plan"
                        )}
                      </Button>
                    ) : (
                      <Button
                        className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90 font-semibold"
                        onClick={() => handleUpgrade("pro")}
                        disabled={billingActionLoading}
                      >
                        {billingActionLoading ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : (
                          "Upgrade"
                        )}
                      </Button>
                    )}
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
                    <div className="p-3 rounded-lg bg-secondary/30">
                      <p className="text-[10px] text-muted-foreground">Video Analyses (this month)</p>
                      <p className="text-sm font-semibold mt-1">
                        {subscription.analyses_used_this_month} /{" "}
                        {subscription.analyses_per_month < 0
                          ? "Unlimited"
                          : subscription.analyses_per_month}
                      </p>
                      <Progress
                        value={
                          subscription.analyses_per_month <= 0
                            ? 0
                            : Math.min(
                                100,
                                (subscription.analyses_used_this_month /
                                  subscription.analyses_per_month) *
                                  100,
                              )
                        }
                        className="h-1 mt-2"
                      />
                    </div>
                    {subscription.plan === "free" && (
                      <div className="p-3 rounded-lg bg-cyan-glow/5 border border-cyan-glow/20 flex flex-col justify-center">
                        <p className="text-xs text-muted-foreground">
                          Need more? Upgrade for higher limits and the full toolset.
                        </p>
                        <Button
                          size="sm"
                          variant="link"
                          className="text-cyan-glow px-0 h-auto justify-start mt-1"
                          onClick={() => handleUpgrade("pro")}
                          disabled={billingActionLoading}
                        >
                          View plans <ExternalLink className="w-3 h-3 ml-1" />
                        </Button>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                <p className="text-sm text-muted-foreground py-4">
                  Couldn't load your billing details. Refresh to try again.
                </p>
              )}
            </CardContent>
          </Card>

          <Card className="bg-card border-border/50">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold">Payment Method</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between p-3 rounded-lg bg-secondary/30">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-7 rounded bg-secondary flex items-center justify-center">
                    <CreditCard className="w-4 h-4 text-muted-foreground" />
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {subscription?.has_stripe_customer
                      ? "Managed securely by Stripe"
                      : "No payment method on file"}
                  </p>
                </div>
                {subscription?.has_stripe_customer && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-xs"
                    onClick={handleManageBilling}
                    disabled={billingActionLoading}
                  >
                    Manage
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Referrals */}
        <TabsContent value="referrals" className="space-y-6">
          <Card className="bg-gradient-to-br from-cyan-glow/10 to-purple-500/10 border-cyan-glow/20">
            <CardHeader className="pb-3">
              <CardTitle className="text-lg font-bold flex items-center gap-2">
                <Gift className="w-5 h-5 text-cyan-glow" />
                Invite Friends, Earn Rewards
              </CardTitle>
              <CardDescription>
                Share ViewMagnet with friends and earn <span className="text-cyan-glow font-semibold">+5 bonus analyses</span> for each signup!
              </CardDescription>
            </CardHeader>
            <CardContent>
              {referralLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-6 h-6 animate-spin text-cyan-glow" />
                </div>
              ) : referralStats ? (
                <div className="space-y-6">
                  {/* Referral Link */}
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-muted-foreground">Your Referral Link</label>
                    <div className="flex gap-2">
                      <Input
                        value={referralStats.referral_link}
                        readOnly
                        className="bg-secondary/50 border-border/50 font-mono text-sm"
                      />
                      <Button
                        onClick={copyReferralLink}
                        className="bg-cyan-glow text-deep-charcoal hover:bg-cyan-glow/90"
                      >
                        <Copy className="w-4 h-4 mr-1" />
                        Copy
                      </Button>
                    </div>
                    <p className="text-[10px] text-muted-foreground">
                      Code: <span className="font-mono text-foreground">{referralStats.referral_code}</span>
                    </p>
                  </div>

                  {/* Share Buttons */}
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-muted-foreground">Share via</label>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={shareOnTwitter}
                        className="border-border/50 hover:bg-[#1DA1F2]/10 hover:text-[#1DA1F2] hover:border-[#1DA1F2]/30"
                      >
                        <Twitter className="w-4 h-4 mr-1" />
                        Twitter
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={shareOnLinkedIn}
                        className="border-border/50 hover:bg-[#0A66C2]/10 hover:text-[#0A66C2] hover:border-[#0A66C2]/30"
                      >
                        <Linkedin className="w-4 h-4 mr-1" />
                        LinkedIn
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={shareOnWhatsApp}
                        className="border-border/50 hover:bg-[#25D366]/10 hover:text-[#25D366] hover:border-[#25D366]/30"
                      >
                        <MessageCircle className="w-4 h-4 mr-1" />
                        WhatsApp
                      </Button>
                    </div>
                  </div>

                  <Separator className="bg-border/30" />

                  {/* Stats */}
                  <div className="grid grid-cols-2 gap-4">
                    <div className="p-4 rounded-lg bg-secondary/30 text-center">
                      <div className="flex items-center justify-center gap-2 mb-1">
                        <Users className="w-4 h-4 text-muted-foreground" />
                        <span className="text-2xl font-bold text-foreground">{referralStats.referral_count}</span>
                      </div>
                      <p className="text-xs text-muted-foreground">Friends Invited</p>
                    </div>
                    <div className="p-4 rounded-lg bg-secondary/30 text-center">
                      <div className="flex items-center justify-center gap-2 mb-1">
                        <Sparkles className="w-4 h-4 text-cyan-glow" />
                        <span className="text-2xl font-bold text-cyan-glow">{referralStats.bonus_analyses_earned}</span>
                      </div>
                      <p className="text-xs text-muted-foreground">Bonus Analyses Earned</p>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-center py-8 text-muted-foreground">
                  Unable to load referral information. Please try again later.
                </p>
              )}
            </CardContent>
          </Card>

          <Card className="bg-card border-border/50">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold">How It Works</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {[
                  { step: "1", title: "Share your link", desc: "Send your unique referral link to friends" },
                  { step: "2", title: "They sign up", desc: "Your friend creates a free ViewMagnet account" },
                  { step: "3", title: "You both win", desc: "You get +5 bonus video analyses instantly!" },
                ].map((item) => (
                  <div key={item.step} className="flex items-start gap-3">
                    <div className="w-6 h-6 rounded-full bg-cyan-glow/20 text-cyan-glow text-xs font-bold flex items-center justify-center flex-shrink-0">
                      {item.step}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-foreground">{item.title}</p>
                      <p className="text-[10px] text-muted-foreground">{item.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Integrations */}
        <TabsContent value="integrations" className="space-y-4">
          <Card className="bg-card border-border/50">
            <CardContent className="p-5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-red-500/10 flex items-center justify-center">
                    <Youtube className="w-5 h-5 text-red-500" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-foreground">YouTube Analytics</p>
                    <p className="text-xs text-muted-foreground">Connected as "John Doe Tech"</p>
                  </div>
                </div>
                <Badge className="bg-emerald-400/10 text-emerald-400 border-emerald-400/20 text-[10px]">
                  <CheckCircle2 className="w-3 h-3 mr-1" />
                  Connected
                </Badge>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-card border-border/50">
            <CardContent className="p-5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-blue-500/10 flex items-center justify-center">
                    <Chrome className="w-5 h-5 text-blue-400" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-foreground">Chrome Extension</p>
                    <p className="text-xs text-muted-foreground">Analyze videos directly on YouTube</p>
                  </div>
                </div>
                <Button variant="outline" size="sm" className="text-xs border-border/50">
                  <ExternalLink className="w-3 h-3 mr-1" />
                  Install
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-card border-border/50">
            <CardContent className="p-5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-amber-glow/10 flex items-center justify-center">
                    <Zap className="w-5 h-5 text-amber-glow" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-foreground">API Tokens</p>
                    <p className="text-xs text-muted-foreground">
                      Personal access tokens for the MCP server, CI scripts, and other automation.
                    </p>
                  </div>
                </div>
                <Button
                  asChild
                  variant="outline"
                  size="sm"
                  className="text-xs border-border/50"
                >
                  <a href="/dashboard/api-tokens">Manage tokens</a>
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-card border-border/50">
            <CardContent className="p-5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-cyan-glow/10 flex items-center justify-center">
                    <Sparkles className="w-5 h-5 text-cyan-glow" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-foreground">MCP server</p>
                    <p className="text-xs text-muted-foreground">
                      Install ViewMagnet in Claude Desktop, Cursor, or Cline with one command.
                    </p>
                  </div>
                </div>
                <Button
                  asChild
                  variant="outline"
                  size="sm"
                  className="text-xs border-border/50"
                >
                  <a href="/mcp">
                    <ExternalLink className="w-3 h-3 mr-1" />
                    Learn more
                  </a>
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
