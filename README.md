# Travel Itinerary Planner

Takes budget, dates and interests, then builds a complete travel plan including flights, hotels and activities.

We believe travellers will reach a booked itinerary faster than planning manually because LLMs are strong at generating many tailored alternatives cheaply. This breaks if made-up or outdated prices and availability show up, so we pull every flight, hotel and price from live search APIs and timestamp each quote. We would know it works if 100% of items in 20 test itineraries are bookable at the quoted price (an integration check) and median time-to-booked-itinerary is at least 50% shorter than a matched group planning the same trip manually.
