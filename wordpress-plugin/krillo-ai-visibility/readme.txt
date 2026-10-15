=== Krillo AI Visibility ===
Contributors: krillo
Tags: ai, chatgpt, woocommerce, seo, ai visibility
Requires at least: 6.0
Tested up to: 7.1
Requires PHP: 7.4
Stable tag: 1.0.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

See where ChatGPT and Gemini rank your store, count visits and orders from AI assistants, and show your rank with a badge.

== Description ==

More shoppers ask ChatGPT or Gemini where to buy. Every month the Krillo Index asks these assistants the buying questions of each store category and ranks the stores they name.

This plugin brings that into WordPress:

* **Your rank on your dashboard.** A dashboard widget shows your rank in the Krillo Index, or tells you if your store is not ranked yet. No account needed.
* **Visits and orders from AI.** With a Krillo plan, paste your pixel key and the plugin counts visits that come from ChatGPT, Gemini, Perplexity and Copilot, and WooCommerce orders from those visits. No personal data is sent.
* **A badge.** Add `[krillo_badge]` to a page, widget or footer. It shows your rank only when AI really names your store, and links to the public ranking.

The plugin makes no AI calls and does not change your products or pages.

== External services ==

This plugin connects to Krillo (krilloai.com), a service for AI visibility of online stores.

* **Rank lookup.** To show your rank on the dashboard and in the badge, the plugin sends your site address (home URL) to https://krilloai.com/api/tools/index-check. This happens at most once every twelve hours, when an administrator opens the dashboard or a page with the badge is shown. No other data is sent.
* **AI visit and order counting (optional, off by default).** Only when you enter a pixel key in Settings > Krillo AI. Then, when a visitor arrives from an AI assistant, the visitor's browser sends the assistant name and your pixel key to https://krilloai.com/api/pixel. On the WooCommerce order received page it also sends the order number, total and currency. No names, email addresses, IP-based profiles or other personal data are sent by the plugin.

Terms of use: https://krilloai.com/terms
Privacy policy: https://krilloai.com/privacy

== Installation ==

1. Install the plugin from Plugins > Add New, or upload the folder to /wp-content/plugins/.
2. Activate it. Your rank appears on the WordPress dashboard.
3. Optional: with a Krillo plan, go to Settings > Krillo AI and paste your pixel key.
4. Optional: add `[krillo_badge]` where you want the badge.

== Frequently Asked Questions ==

= Do I need a Krillo account? =

No. The rank and the badge work without an account. The pixel key comes with a Krillo plan.

= Which countries are measured? =

The Krillo Index measures the Netherlands and Belgium today, with more countries coming. If your store is not ranked yet, the widget tells you.

= Can I pay for a better rank? =

No. The index has no paid positions.

== Changelog ==

= 1.0.0 =
* First version: dashboard rank, AI visit and order counting, badge shortcode.
