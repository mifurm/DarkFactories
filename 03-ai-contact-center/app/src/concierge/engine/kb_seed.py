"""Synthetic Contoso Home Retail knowledge base (returns, damage, refunds, delivery, installation, warranty, billing, loyalty,
privacy, product care, service). All facts are fictional and kept consistent with the default policy parameters."""

from __future__ import annotations

from typing import Any


def _d(doc_id: str, title: str, category: str, tags: str, text: str, lang: str = "en") -> dict[str, Any]:
    return {"id": doc_id, "title": title, "category": category, "tags": [t.strip() for t in tags.split(",")], "lang": lang, "text": text.strip(), "source": "seed"}


KB_DOCS: list[dict[str, Any]] = [
    _d("returns-001", "Returns policy (30 days)", "returns", "returns,refund,window", """
# Returns policy
## Return window
You can return most items within 30 days of delivery, free of charge. The item must be unused and in its original condition. The 30-day window starts on the delivery date shown in your order.
## Free collection
For bulky items (sofas, mattresses, wardrobes, large appliances) we collect the item at your home for free. Small items can be returned with a prepaid label.
## Refund
After we collect or receive the item, the refund goes to the original payment method within 5-7 business days.
Keywords (de/fr/es): Rückgabe, Retoure, Rücksendung, retour, remboursement, devolución.
"""),
    _d("returns-002", "Items that cannot be returned", "returns", "returns,exceptions,hygiene,custom", """
# Items that cannot be returned
## Exceptions
Custom-made or made-to-measure furniture, opened mattress protectors and items used for hygiene reasons cannot be returned unless they are faulty or arrived damaged.
Clearance items marked "final sale" are excluded from the 30-day return window but keep their warranty.
## Statutory rights
Your statutory rights for faulty goods are not affected by this policy.
"""),
    _d("returns-003", "Scheduling a return pickup", "returns", "returns,pickup,slots,collection", """
# Scheduling a return pickup
## Pickup windows
Pickups take place Monday to Friday in two windows: 09:00-13:00 and 13:00-17:00. Our customer-care agents can book the next available window for you.
## Preparing the pickup
Please make sure the item is accessible and, for sofas and mattresses, wrapped if possible. You do not need to repack appliances in the original box. Two carriers collect bulky items.
## Missed pickups
If you miss a pickup appointment it can be rebooked once at no charge.
"""),
    _d("returns-004", "Exchanges and replacements", "returns", "exchange,replacement,lead time", """
# Exchanges and replacements
## Replacement
If an item arrived damaged or faulty we send an identical replacement at no cost. Replacements are delivered within 3-10 working days depending on stock; the damaged item is collected when the replacement is delivered or earlier on request.
## Different model
For a different model we process a return and a new order; the price difference is charged or refunded.
"""),
    _d("returns-005", "Return costs and carrier claims", "returns", "returns,costs,carrier,claims", """
# Return costs and carrier claims
Returns of bulky items and all damaged-on-delivery cases are free for you. Contoso Home handles any claim against the carrier (NordFreight, SwiftHaul, BlueRoute); you never need to contact the carrier yourself.
"""),
    _d("damage-001", "Damaged on delivery", "damage", "damage,delivery,transit,replacement,refund", """
# Damaged on delivery
## Report within 14 days
Report visible transit damage within 14 days of delivery. We are sorry for the inconvenience - you do not need to keep the packaging.
## Your options
You can choose a free replacement or a full refund of the damaged item. A free pickup of the damaged item is arranged either way. Photos help but are not required for orders under 500 EUR; for orders of 500 EUR or more please send photos by e-mail or upload them in your account.
## Refund timing
A refund is released after the item has been collected and arrives at our warehouse, normally 5-7 business days after pickup.
Keywords (de/fr/es): beschädigt, Transportschaden, endommagé, dañado.
"""),
    _d("damage-002", "Schaden bei der Lieferung (Deutsch)", "damage", "schaden,lieferung,beschädigt,ersatz,erstattung", """
# Schaden bei der Lieferung
## Meldung innerhalb von 14 Tagen
Sichtbare Transportschäden melden Sie bitte innerhalb von 14 Tagen nach der Lieferung. Die Verpackung müssen Sie nicht aufbewahren.
## Ihre Optionen
Sie können zwischen einem kostenlosen Ersatz und der vollständigen Erstattung des beschädigten Artikels wählen. Die kostenlose Abholung des beschädigten Artikels organisieren wir in beiden Fällen.
## Erstattung
Die Erstattung erfolgt nach Eingang des Artikels in unserem Lager, in der Regel 5-7 Werktage nach der Abholung, auf die ursprüngliche Zahlungsart.
""", "de"),
    _d("damage-003", "Photo evidence for damage claims", "damage", "damage,photos,evidence,claim", """
# Photo evidence for damage claims
## When photos are needed
For orders under 500 EUR photos are optional. For orders of 500 EUR or more, or when damage is disputed, please provide 2-4 photos: the damaged area, the whole item, and the packaging label.
## How to send
Upload photos in your account under "My orders" or reply to the confirmation e-mail. We review photos within one business day.
"""),
    _d("damage-004", "Damage reported after 14 days", "damage", "damage,late,exception,goodwill", """
# Damage reported after 14 days
Damage reported later than 14 days after delivery is handled as a warranty or goodwill case by a specialist colleague. Please contact us and mention the delivery date; the specialist team decides individually.
"""),
    _d("returns-006", "Rückgabe und Widerruf (Deutsch)", "returns", "rückgabe,widerruf,retoure,frist", """
# Rückgabe und Widerruf
## Rückgabefrist
Sie können die meisten Artikel innerhalb von 30 Tagen nach Lieferung kostenlos zurückgeben. Der gesetzliche Widerruf von 14 Tagen bleibt unberührt.
## Abholung
Sperrige Artikel wie Sofas, Matratzen und Schränke holen wir kostenlos bei Ihnen ab.
""", "de"),
    _d("refunds-001", "Refund timing and method", "refunds", "refund,timing,payment method", """
# Refund timing and method
## How refunds are paid
Refunds always go back to the original payment method. Card refunds appear within 5-7 business days after we collect the item; PayPal refunds are usually faster. Invoice orders are credited to your customer account.
## Who can approve
Our customer-care agents can refund up to 500 EUR immediately. Refunds above 500 EUR are reviewed by a specialist and usually approved within one business day.
"""),
    _d("refunds-002", "Partial refunds and keep-it discounts", "refunds", "refund,partial,keep,discount", """
# Partial refunds and keep-it discounts
For minor cosmetic damage you can keep the item and receive a partial refund of 10-30 % of the item price, depending on the damage. The amount is agreed before the refund is issued.
"""),
    _d("refunds-003", "Checking the status of a refund", "refunds", "refund,status,delay", """
# Checking the status of a refund
Ask customer care or look in "My orders > Refunds". A refund shows "issued" once we have paid it; banks may need another 2-3 business days to display it. If more than 10 business days have passed since the pickup scan, contact us and we open an investigation.
"""),
    _d("refunds-004", "Goodwill gestures and delay compensation", "refunds", "goodwill,compensation,voucher,delay", """
# Goodwill gestures and delay compensation
## Guidelines
For deliveries delayed by more than 3 days or a missed appointment on our side, customer-care agents may offer a goodwill credit of up to 50 EUR. Credits are limited to 100 EUR per customer in any 90 days, are not paid out in cash and are valid for 12 months.
## Larger amounts
Compensation above these limits is decided by a specialist colleague.
"""),
    _d("delivery-001", "Delivery options and windows", "delivery", "delivery,windows,standard,bulky", """
# Delivery options and windows
Standard delivery takes 3-7 working days; bulky items (sofas, wardrobes, appliances) 5-10 working days. You choose a 4-hour delivery window (08:00-12:00, 12:00-16:00 or 16:00-20:00) and receive a notification the evening before.
"""),
    _d("delivery-002", "Tracking your delivery and status meanings", "delivery", "tracking,status,shipment", """
# Tracking your delivery
Statuses: order received, label created, in transit, out for delivery, delivered, delayed, exception. "Delayed" means the carrier expects to miss the planned date; we update the date as soon as the carrier confirms it. Tracking is available in "My orders" and from customer care.
"""),
    _d("delivery-003", "Rescheduling a delivery", "delivery", "reschedule,delivery,slot,free", """
# Rescheduling a delivery
You can reschedule a delivery free of charge up to 24 hours before the delivery window. Customer care offers the next available windows (Monday to Friday). Within 24 hours the carrier decides; we will try to help.
"""),
    _d("delivery-004", "Missed delivery attempts", "delivery", "missed,redelivery,carrier", """
# Missed delivery attempts
If nobody is home the carrier leaves a card and tries once more the next working day. After the second failed attempt the parcel returns to our depot; we rebook a new window free of charge once.
"""),
    _d("delivery-005", "Delivery delays", "delivery", "delay,late,carrier hub,compensation", """
# Delivery delays
Delays are usually caused by carrier hub capacity or weather. We update the new delivery date as soon as it is confirmed. For delays of more than 3 days customer care may offer a goodwill credit of up to 50 EUR (see Goodwill gestures).
"""),
    _d("delivery-006", "Measuring and access (stairs, doorways)", "delivery", "stairs,access,measure,upper floor", """
# Measuring and access
Please measure doorways, stairs and lifts before ordering. Our two-person teams carry items to the room of your choice, including upper floors, but cannot dismantle doors or windows. Tell us about narrow access when you book.
"""),
    _d("delivery-007", "Changing the delivery address", "delivery", "address,change,dispatch,verification", """
# Changing the delivery address
The address can be changed free of charge until the order is dispatched. Because address changes are a common fraud pattern, customer care verifies you with a one-time code and a security question first. After dispatch please contact the carrier; we will help with the contact details.
"""),
    _d("delivery-008", "Carriers we work with", "delivery", "carrier,NordFreight,SwiftHaul,BlueRoute", """
# Carriers
Contoso Home delivers with the freight carriers NordFreight, SwiftHaul and BlueRoute. The carrier is shown in your order tracking. All carriers use two-person teams for bulky items.
"""),
    _d("install-001", "Installation service overview", "installation", "installation,appliance,assembly,price", """
# Installation service
Appliance installation (washing machines, dishwashers, ovens) costs 49 EUR per appliance; furniture assembly costs 39 EUR per item. Appointments last about 90 minutes and are booked together with the delivery or afterwards.
"""),
    _d("install-002", "Missed installation appointments", "installation", "installation,missed,rebooking,goodwill", """
# Missed installation appointments
If our installer misses an appointment you are entitled to priority rebooking within 48 hours and a goodwill credit of 30 EUR. If two appointments are missed the case is passed to a senior colleague.
"""),
    _d("install-003", "Washing machine installation prerequisites", "installation", "washing machine,water,connection", """
# Washing machine installation
Please provide a cold-water tap, a drain and a free power socket within 1.5 m. Our team connects the machine, runs a test cycle and removes the transport bolts. We cannot create new water or drain connections.
"""),
    _d("install-004", "Furniture assembly", "installation", "assembly,wardrobe,bed", """
# Furniture assembly
Wardrobes, beds and tables can be assembled in the room of your choice. Please clear the space. Assembly of wall-mounted units requires suitable walls; the team will advise on site.
"""),
    _d("install-005", "What we do not install", "installation", "limits,gas,electrical", """
# What we do not install
We do not connect gas appliances, perform electrical rewiring, or install appliances in kitchens that do not meet connection requirements. Contact a licensed professional for these jobs.
"""),
    _d("warranty-001", "Warranty overview", "warranty", "warranty,guarantee,months", """
# Warranty overview
All products carry a 24-month warranty from the delivery date; mattresses carry 36 months. The warranty covers defects in materials and workmanship that were not caused by misuse.
"""),
    _d("warranty-002", "How to make a warranty claim", "warranty", "warranty,claim,repair,replacement", """
# How to make a warranty claim
Contact customer care with your order number and a short description (photos help). We decide within 10 working days whether the item is repaired, replaced or refunded. If the item cannot be repaired we replace it.
"""),
    _d("warranty-003", "What the warranty does not cover", "warranty", "warranty,exclusions,wear", """
# What the warranty does not cover
Normal wear and tear, damage from misuse, accidents, unauthorised repairs, commercial use and cosmetic changes such as fading in sunlight are not covered.
"""),
    _d("warranty-004", "Garantie und Gewährleistung (Deutsch)", "warranty", "garantie,gewährleistung,reparatur", """
# Garantie und Gewährleistung
Alle Produkte haben 24 Monate Garantie ab Lieferdatum, Matratzen 36 Monate. Bitte melden Sie einen Mangel mit Bestellnummer und kurzer Beschreibung; wir entscheiden innerhalb von 10 Werktagen über Reparatur, Ersatz oder Erstattung.
""", "de"),
    _d("billing-001", "Payment methods", "billing", "payment,methods,card,paypal,invoice,instalments", """
# Payment methods
We accept Visa, Mastercard, PayPal and, for approved customers, payment by invoice. Orders above 300 EUR can be paid in 6 interest-free instalments. We never accept cash or cryptocurrency.
"""),
    _d("billing-002", "Secure payment hand-off", "billing", "payment,pci,secure link,card number", """
# Secure payment hand-off
Our assistants and agents never take card numbers, expiry dates or security codes in chat or on the phone. If a payment is needed you receive a secure payment link or, on a call, enter the digits on your phone keypad so that nobody hears or sees them.
"""),
    _d("billing-003", "Invoices and VAT receipts", "billing", "invoice,vat,receipt", """
# Invoices and VAT receipts
Invoices are available in "My orders" as PDF and are e-mailed on dispatch. Customer care can resend an invoice to the e-mail address on file. VAT invoices for businesses can be issued on request.
"""),
    _d("billing-004", "Double charges and authorisation holds", "billing", "double charge,authorisation,hold", """
# Double charges and authorisation holds
A pending card authorisation can look like a second charge. Authorisations that are not captured drop off within 5-7 days. If you see two captured charges for one order contact customer care; we investigate and refund duplicates.
"""),
    _d("loyalty-001", "Contoso Home Club", "loyalty", "loyalty,points,vip,tiers", """
# Contoso Home Club
Members earn 1 point per euro spent; 500 points are worth a 10 EUR voucher. VIP members (annual spend above 3,000 EUR) get priority customer care, free delivery and extended returns of 45 days.
"""),
    _d("loyalty-002", "Vouchers and promo codes", "loyalty", "voucher,promo,validity", """
# Vouchers and promo codes
Vouchers are valid for 12 months and cannot be paid out in cash. One promo code can be used per order; codes cannot be combined with Club vouchers unless stated.
"""),
    _d("privacy-001", "Data protection and your rights", "privacy", "gdpr,privacy,data,deletion", """
# Data protection and your rights
You can request access to, correction or deletion of your personal data. We respond within 30 days. Customer care can start the request after verifying your identity; the data protection team completes it.
"""),
    _d("privacy-002", "Call and chat recording, AI disclosure", "privacy", "recording,ai,disclosure,consent", """
# Call and chat recording and AI disclosure
Every conversation starts with a disclosure that you are talking to an AI assistant and that the conversation may be recorded for quality and training. You can decline recording; service continues without recording or a human colleague takes over. Recordings are kept for 12 months and then deleted.
"""),
    _d("privacy-003", "Why we verify your identity", "privacy", "verification,otp,security", """
# Why we verify your identity
To protect your account we send a one-time code to the phone number on file before showing order details or making changes. We never ask for passwords, card numbers or full bank details, and you should never share a code with anyone who contacts you unprompted.
"""),
    _d("care-001", "Sofa care and cleaning", "product-care", "sofa,care,cleaning,fabric", """
# Sofa care
Vacuum weekly with an upholstery nozzle. Treat spills immediately by blotting, not rubbing. Fabric sofas: use a mild soap solution; do not use bleach. Rotate loose cushions monthly. Keep sofas away from direct sunlight and radiators.
"""),
    _d("care-002", "Mattress care", "product-care", "mattress,care,rotation", """
# Mattress care
Rotate the mattress head-to-foot every 3 months and air the room daily. New foam mattresses may have a slight odour for 24-48 hours. Use a breathable protector; do not wash the mattress cover above 30 degrees unless the label says so.
"""),
    _d("care-003", "Washing machine error codes", "troubleshooting", "washing machine,error,E18,E21", """
# Washing machine error codes (Vera 8 kg)
E18: water inlet problem - check the tap and the inlet filter. E21: drain problem - clean the drain pump filter at the front bottom. If the code persists after cleaning, contact customer care to arrange a warranty visit.
"""),
    _d("care-004", "Dishwasher not draining", "troubleshooting", "dishwasher,drain,filter", """
# Dishwasher not draining
Switch the dishwasher off, remove the bottom rack and clean the filter. Check that the drain hose is not kinked. If water remains after cleaning, contact customer care for a warranty visit.
"""),
    _d("care-005", "Assembly tips for wardrobes and beds", "product-care", "assembly,wardrobe,bed,tighten", """
# Assembly tips
Tighten all screws again after two weeks of use as wood settles. Assemble on a soft surface to protect panels and floor. Do not over-tighten cam locks.
"""),
    _d("care-006", "Safety: gas smell, smoke or sparks", "safety", "safety,gas,smoke,sparks,emergency", """
# Safety first
If you smell gas, see smoke or sparks or get an electric shock from a product: stop using it, switch off power at the fuse box if safe, ventilate, leave the room if there is a gas smell and call the emergency number (112). Then contact us - safety reports are escalated to a specialist immediately.
"""),
    _d("service-001", "Opening hours and channels", "service", "hours,channels,contact", """
# Opening hours and channels
The AI assistant is available 24/7 by chat and voice. Human colleagues are available every day from 07:00 to 22:00 CET and can be reached from the assistant at any time; outside these hours you can request a callback.
"""),
    _d("service-002", "Accessibility and extra support", "service", "accessibility,vulnerable,callback,support", """
# Accessibility and extra support
We offer callbacks, large-print invoices and relay-service support. Customers who tell us they need extra support (for example because of age, illness or bereavement) are connected to our dedicated care team with priority.
"""),
    _d("service-003", "Complaints procedure", "service", "complaint,escalation,ombudsman", """
# Complaints procedure
Tell us what went wrong and we acknowledge your complaint immediately. A senior colleague responds within 5 working days. If you remain dissatisfied you can contact the consumer arbitration body in your country; we provide the details on request.
"""),
    _d("service-004", "Delivery to a different person or neighbour", "delivery", "neighbour,authorised,signature", """
# Delivery to a neighbour
You can authorise a neighbour or another person to accept the delivery by telling the carrier on the day. Please make sure the item is checked for damage on receipt and report damage within 14 days.
"""),
    _d("service-005", "Sustainability and old-appliance take-back", "service", "sustainability,recycling,take-back", """
# Old-appliance take-back
When installing a new appliance our team takes your old appliance for recycling free of charge if it is disconnected and accessible. Furniture take-back is available for 29 EUR per item.
"""),
]
