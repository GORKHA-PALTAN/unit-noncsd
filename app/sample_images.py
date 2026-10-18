"""Generates simple illustrated SVG product images for the SAMPLE catalogue (no external assets needed)."""

ICONS = {
    "electronics": '<rect x="-70" y="-55" width="140" height="90" rx="8" fill="{dark}"/><rect x="-62" y="-47" width="124" height="74" rx="4" fill="{accent}"/>'
                   '<path d="M-62 27 L-20 -10 L10 15 L30 0 L62 27Z" fill="{dark}" opacity=".25"/><rect x="-8" y="35" width="16" height="16" fill="{dark}"/>'
                   '<rect x="-36" y="50" width="72" height="8" rx="4" fill="{dark}"/>',
    "mobile": '<rect x="-38" y="-72" width="76" height="144" rx="14" fill="{dark}"/><rect x="-32" y="-62" width="64" height="118" rx="6" fill="{accent}"/>'
              '<circle cx="0" cy="64" r="4" fill="#fff" opacity=".7"/><rect x="-12" y="-68" width="24" height="3" rx="1.5" fill="#fff" opacity=".5"/>'
              '<circle cx="-12" cy="-40" r="10" fill="#fff" opacity=".35"/><rect x="-22" y="-10" width="44" height="6" rx="3" fill="#fff" opacity=".5"/>'
              '<rect x="-22" y="4" width="30" height="6" rx="3" fill="#fff" opacity=".35"/>',
    "computers": '<rect x="-62" y="-52" width="124" height="80" rx="6" fill="{dark}"/><rect x="-55" y="-45" width="110" height="66" rx="3" fill="{accent}"/>'
                 '<path d="M-80 34 L80 34 L70 48 L-70 48Z" fill="{dark}"/><rect x="-14" y="36" width="28" height="4" rx="2" fill="#fff" opacity=".4"/>'
                 '<rect x="-40" y="-30" width="50" height="6" rx="3" fill="#fff" opacity=".45"/><rect x="-40" y="-18" width="70" height="6" rx="3" fill="#fff" opacity=".3"/>',
    "audio": '<path d="M-52 10 A52 56 0 0 1 52 10" fill="none" stroke="{dark}" stroke-width="12" stroke-linecap="round"/>'
             '<rect x="-66" y="0" width="30" height="52" rx="12" fill="{accent}"/><rect x="36" y="0" width="30" height="52" rx="12" fill="{accent}"/>'
             '<rect x="-60" y="8" width="18" height="36" rx="8" fill="{dark}" opacity=".35"/><rect x="42" y="8" width="18" height="36" rx="8" fill="{dark}" opacity=".35"/>',
    "clothing": '<path d="M-28 -62 L-70 -40 L-54 -6 L-40 -14 L-40 66 L40 66 L40 -14 L54 -6 L70 -40 L28 -62 Q0 -40 -28 -62Z" fill="{accent}"/>'
                '<path d="M-28 -62 Q0 -40 28 -62 Q0 -30 -28 -62Z" fill="{dark}" opacity=".35"/><rect x="-14" y="-6" width="28" height="22" rx="4" fill="#fff" opacity=".35"/>',
    "shoes": '<path d="M-80 30 Q-80 -6 -50 -14 L-20 -40 Q-6 -46 6 -36 L20 -16 Q60 -10 78 10 Q86 22 80 34 Z" fill="{accent}"/>'
             '<path d="M-84 30 L84 30 Q86 44 76 46 L-78 46 Q-88 44 -84 30Z" fill="{dark}"/>'
             '<path d="M-18 -30 L4 -10 M-28 -22 L-6 -2 M-38 -14 L-16 6" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".7"/>',
    "watches": '<rect x="-20" y="-80" width="40" height="160" rx="12" fill="{dark}"/><circle cx="0" cy="0" r="46" fill="{dark}"/>'
               '<circle cx="0" cy="0" r="38" fill="{accent}"/><path d="M0 0 L0 -26 M0 0 L18 8" stroke="#fff" stroke-width="5" stroke-linecap="round"/>'
               '<circle cx="0" cy="0" r="4" fill="#fff"/><rect x="44" y="-8" width="10" height="16" rx="3" fill="{dark}"/>',
    "appliances": '<rect x="-56" y="-70" width="112" height="140" rx="12" fill="{accent}"/><rect x="-56" y="-70" width="112" height="30" rx="12" fill="{dark}" opacity=".3"/>'
                  '<circle cx="0" cy="14" r="38" fill="{dark}"/><circle cx="0" cy="14" r="28" fill="#fff" opacity=".35"/>'
                  '<circle cx="-36" cy="-55" r="5" fill="#fff"/><circle cx="-20" cy="-55" r="5" fill="#fff" opacity=".6"/>',
    "kitchen": '<path d="M-60 -10 L60 -10 L52 50 Q50 62 38 62 L-38 62 Q-50 62 -52 50Z" fill="{accent}"/>'
               '<rect x="-68" y="-22" width="136" height="16" rx="8" fill="{dark}"/><rect x="-12" y="-40" width="24" height="14" rx="6" fill="{dark}"/>'
               '<rect x="60" y="2" width="28" height="10" rx="5" fill="{dark}"/><rect x="-88" y="2" width="28" height="10" rx="5" fill="{dark}"/>',
    "sports": '<rect x="-24" y="-8" width="48" height="16" rx="6" fill="{dark}"/><rect x="-62" y="-40" width="26" height="80" rx="8" fill="{accent}"/>'
              '<rect x="36" y="-40" width="26" height="80" rx="8" fill="{accent}"/><rect x="-82" y="-26" width="20" height="52" rx="6" fill="{dark}"/>'
              '<rect x="62" y="-26" width="20" height="52" rx="6" fill="{dark}"/>',
    "care": '<rect x="-34" y="-30" width="68" height="100" rx="16" fill="{accent}"/><rect x="-16" y="-58" width="32" height="30" rx="4" fill="{dark}"/>'
            '<rect x="-24" y="-70" width="48" height="14" rx="5" fill="{dark}"/><rect x="-22" y="0" width="44" height="34" rx="6" fill="#fff" opacity=".5"/>',
    "accessories": '<path d="M-26 -30 Q-26 -66 0 -66 Q26 -66 26 -30" fill="none" stroke="{dark}" stroke-width="9"/>'
                   '<path d="M-70 -30 L70 -30 L60 64 L-60 64Z" fill="{accent}"/><rect x="-70" y="-30" width="140" height="22" fill="{dark}" opacity=".25"/>'
                   '<rect x="-12" y="-14" width="24" height="16" rx="3" fill="{dark}"/>',
}


def product_svg(icon_key, accent, dark, label, sub_label=""):
    icon = ICONS.get(icon_key, ICONS["accessories"]).format(accent=accent, dark=dark)
    safe = lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" width="400" height="400">
<defs><radialGradient id="g" cx="50%" cy="42%" r="60%"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="#eceef3"/></radialGradient></defs>
<rect width="400" height="400" fill="url(#g)"/>
<circle cx="200" cy="180" r="118" fill="{accent}" opacity=".12"/>
<g transform="translate(200 180) scale(1.25)">{icon}</g>
<ellipse cx="200" cy="300" rx="90" ry="8" fill="#000" opacity=".06"/>
<text x="200" y="345" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="20" font-weight="700" fill="#2b3047">{safe(label)[:26]}</text>
<text x="200" y="370" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="14" fill="#7a7f94">{safe(sub_label)[:34]}</text>
<rect x="14" y="14" width="76" height="24" rx="12" fill="#2b3047" opacity=".85"/>
<text x="52" y="31" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="12" font-weight="700" fill="#fff" letter-spacing="1">SAMPLE</text>
</svg>"""


PLACEHOLDER = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><rect width="400" height="400" fill="#eceef3"/>
<rect x="130" y="120" width="140" height="110" rx="10" fill="none" stroke="#a5a9ba" stroke-width="10"/><circle cx="170" cy="160" r="14" fill="#a5a9ba"/>
<path d="M140 222 L185 180 L215 205 L235 190 L262 222Z" fill="#a5a9ba"/><text x="200" y="285" text-anchor="middle" font-family="Arial" font-size="20" fill="#7a7f94">No image</text></svg>"""
