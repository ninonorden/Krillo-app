<?php
/**
 * Plugin Name:       Krillo AI Visibility
 * Plugin URI:        https://krilloai.com/tools
 * Description:       See where ChatGPT and Gemini rank your store in the Krillo Index, count visits and orders that come from AI assistants, and show your rank with a badge.
 * Version:           1.0.0
 * Requires at least: 6.0
 * Requires PHP:      7.4
 * Author:            Krillo
 * Author URI:        https://krilloai.com
 * License:           GPLv2 or later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       krillo-ai-visibility
 *
 * Stap 95 (15 oktober 2026). Waarom: wordpress.org is, net als de Shopify App
 * Store, een plek waar winkeliers zelf zoeken. Deze plugin doet drie dingen en
 * niets meer: de plek in de index tonen in het dashboard van WordPress, de
 * Krillo-pixel plaatsen zonder code te plakken, en een badge via [krillo_badge].
 * Geen AI-aanroepen, geen persoonsgegevens, en alleen contact met krilloai.com
 * zoals beschreven in readme.txt (External services).
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'KRILLO_AIV_API', 'https://krilloai.com' );

/* ---------------------------------------------------------------- Instellingen */

function krillo_aiv_register_settings() {
	register_setting(
		'krillo_aiv',
		'krillo_aiv_pixel_key',
		array(
			'type'              => 'string',
			'sanitize_callback' => 'krillo_aiv_sanitize_key',
			'default'           => '',
		)
	);
}
add_action( 'admin_init', 'krillo_aiv_register_settings' );

function krillo_aiv_sanitize_key( $value ) {
	$value = sanitize_text_field( (string) $value );
	return preg_match( '/^[A-Za-z0-9_-]{8,80}$/', $value ) ? $value : '';
}

function krillo_aiv_menu() {
	add_options_page(
		__( 'Krillo AI Visibility', 'krillo-ai-visibility' ),
		__( 'Krillo AI', 'krillo-ai-visibility' ),
		'manage_options',
		'krillo-ai-visibility',
		'krillo_aiv_settings_page'
	);
}
add_action( 'admin_menu', 'krillo_aiv_menu' );

function krillo_aiv_settings_page() {
	if ( ! current_user_can( 'manage_options' ) ) {
		return;
	}
	?>
	<div class="wrap">
		<h1><?php esc_html_e( 'Krillo AI Visibility', 'krillo-ai-visibility' ); ?></h1>
		<p><?php esc_html_e( 'Your rank in the Krillo Index is shown on your WordPress dashboard. No setup needed.', 'krillo-ai-visibility' ); ?></p>
		<form method="post" action="options.php">
			<?php settings_fields( 'krillo_aiv' ); ?>
			<table class="form-table" role="presentation">
				<tr>
					<th scope="row"><label for="krillo_aiv_pixel_key"><?php esc_html_e( 'Pixel key (optional)', 'krillo-ai-visibility' ); ?></label></th>
					<td>
						<input name="krillo_aiv_pixel_key" id="krillo_aiv_pixel_key" type="text" class="regular-text" value="<?php echo esc_attr( get_option( 'krillo_aiv_pixel_key', '' ) ); ?>">
						<p class="description"><?php esc_html_e( 'With a Krillo plan, paste the pixel key from your dashboard (Plan page). The plugin then counts visits and WooCommerce orders that come from ChatGPT, Gemini, Perplexity and Copilot. No personal data is sent. Leave empty to turn it off.', 'krillo-ai-visibility' ); ?></p>
					</td>
				</tr>
			</table>
			<?php submit_button(); ?>
		</form>
		<h2><?php esc_html_e( 'Badge', 'krillo-ai-visibility' ); ?></h2>
		<p><?php esc_html_e( 'Put the shortcode [krillo_badge] in a page, a widget or your footer. It shows your rank only when AI names your store, and links to the public ranking.', 'krillo-ai-visibility' ); ?></p>
	</div>
	<?php
}

/* ------------------------------------------------------------- Plek ophalen */

/**
 * De plek van deze site in de index, twaalf uur bewaard (transient).
 * Geeft een array of null.
 */
function krillo_aiv_rank() {
	$cached = get_transient( 'krillo_aiv_rank' );
	if ( false !== $cached ) {
		return is_array( $cached ) ? $cached : null;
	}
	$response = wp_remote_post(
		KRILLO_AIV_API . '/api/tools/index-check',
		array(
			'timeout' => 10,
			'headers' => array( 'Content-Type' => 'application/json' ),
			'body'    => wp_json_encode( array( 'url' => home_url( '/' ) ) ),
		)
	);
	$data = null;
	if ( ! is_wp_error( $response ) && 200 === (int) wp_remote_retrieve_response_code( $response ) ) {
		$decoded = json_decode( wp_remote_retrieve_body( $response ), true );
		if ( is_array( $decoded ) ) {
			$data = $decoded;
		}
	}
	set_transient( 'krillo_aiv_rank', $data ? $data : 'none', $data ? 12 * HOUR_IN_SECONDS : HOUR_IN_SECONDS );
	return $data;
}

/* --------------------------------------------------------- Dashboard-widget */

function krillo_aiv_dashboard_widget() {
	$rank = krillo_aiv_rank();
	if ( ! $rank ) {
		echo '<p>' . esc_html__( 'Krillo could not be reached right now. Try again later.', 'krillo-ai-visibility' ) . '</p>';
		return;
	}
	echo '<p><strong>' . esc_html( isset( $rank['kop'] ) ? $rank['kop'] : '' ) . '</strong></p>';
	if ( ! empty( $rank['gevonden'] ) && ! empty( $rank['pagina'] ) ) {
		echo '<p><a href="' . esc_url( KRILLO_AIV_API . $rank['pagina'] ) . '" target="_blank" rel="noopener">' . esc_html__( 'See the full ranking', 'krillo-ai-visibility' ) . '</a></p>';
	} elseif ( ! empty( $rank['uitleg'] ) ) {
		echo '<p>' . esc_html( $rank['uitleg'] ) . '</p>';
	}
	echo '<p><a class="button button-primary" href="' . esc_url( KRILLO_AIV_API . '/?winkel=' . rawurlencode( wp_parse_url( home_url( '/' ), PHP_URL_HOST ) ) . '#scan' ) . '" target="_blank" rel="noopener">' . esc_html__( 'See the questions you lose', 'krillo-ai-visibility' ) . '</a></p>';
}

function krillo_aiv_add_dashboard_widget() {
	if ( current_user_can( 'manage_options' ) ) {
		wp_add_dashboard_widget( 'krillo_aiv_widget', __( 'Your rank in AI answers (Krillo)', 'krillo-ai-visibility' ), 'krillo_aiv_dashboard_widget' );
	}
}
add_action( 'wp_dashboard_setup', 'krillo_aiv_add_dashboard_widget' );

/* ------------------------------------------------------------------ Badge */

function krillo_aiv_badge_shortcode() {
	$rank = krillo_aiv_rank();
	// Alleen als AI de winkel echt noemt: nooit een lege of verzonnen badge.
	if ( ! $rank || empty( $rank['gevonden'] ) || empty( $rank['genoemd'] ) || empty( $rank['positie'] ) ) {
		return '';
	}
	$url  = KRILLO_AIV_API . $rank['pagina'] . '?ref=wordpress-badge';
	$text = sprintf(
		/* translators: 1: rank, 2: number of stores, 3: category name */
		__( '#%1$d of %2$d in the Krillo Index for %3$s', 'krillo-ai-visibility' ),
		(int) $rank['positie'],
		(int) $rank['van'],
		$rank['categorie']
	);
	return '<a class="krillo-badge" href="' . esc_url( $url ) . '" target="_blank" rel="noopener" style="display:inline-flex;gap:8px;align-items:center;padding:8px 12px;border:1px solid #E7E7E4;border-radius:10px;background:#fff;color:#0A0A0B;text-decoration:none;font:500 14px/1.3 system-ui,sans-serif;"><strong>KRILLO</strong> ' . esc_html( $text ) . '</a>';
}
add_shortcode( 'krillo_badge', 'krillo_aiv_badge_shortcode' );

/* ------------------------------------------------------------------ Pixel */

function krillo_aiv_pixel() {
	$key = get_option( 'krillo_aiv_pixel_key', '' );
	if ( '' === $key || is_admin() ) {
		return;
	}
	wp_enqueue_script( 'krillo-aiv-pixel', plugins_url( 'pixel.js', __FILE__ ), array(), '1.0.0', false );
	wp_add_inline_script(
		'krillo-aiv-pixel',
		'window.krilloPixel = ' . wp_json_encode( array( 'k' => $key, 'u' => KRILLO_AIV_API . '/api/pixel' ) ) . ';',
		'before'
	);
	// WooCommerce: het bedrag van de bestelling op de bedankpagina, zonder persoonsgegevens.
	if ( function_exists( 'is_order_received_page' ) && is_order_received_page() ) {
		global $wp;
		$order_id = isset( $wp->query_vars['order-received'] ) ? absint( $wp->query_vars['order-received'] ) : 0;
		$order    = $order_id && function_exists( 'wc_get_order' ) ? wc_get_order( $order_id ) : null;
		if ( $order ) {
			wp_add_inline_script(
				'krillo-aiv-pixel',
				'window.krilloOrder = ' . wp_json_encode(
					array(
						'id'       => (string) $order->get_id(),
						'total'    => (string) $order->get_total(),
						'currency' => (string) $order->get_currency(),
					)
				) . ';',
				'before'
			);
		}
	}
}
add_action( 'wp_enqueue_scripts', 'krillo_aiv_pixel' );

function krillo_aiv_settings_link( $links ) {
	array_unshift( $links, '<a href="' . esc_url( admin_url( 'options-general.php?page=krillo-ai-visibility' ) ) . '">' . esc_html__( 'Settings', 'krillo-ai-visibility' ) . '</a>' );
	return $links;
}
add_filter( 'plugin_action_links_' . plugin_basename( __FILE__ ), 'krillo_aiv_settings_link' );

register_deactivation_hook( __FILE__, 'krillo_aiv_deactivate' );
function krillo_aiv_deactivate() {
	delete_transient( 'krillo_aiv_rank' );
}
