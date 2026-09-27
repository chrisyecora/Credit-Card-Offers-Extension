ALTER TABLE banks ADD COLUMN offers_url TEXT;

INSERT INTO banks (slug, name, offers_url) VALUES
    ('capital_one', 'Capital One', 'https://capitaloneoffers.com'),
    ('american_express', 'American Express', 'https://global.americanexpress.com/offers/eligible'),
    ('chase', 'Chase', 'https://secure.chase.com/web/auth/dashboard#/dashboard/merchantOffers/offer-hub')
ON CONFLICT(slug) DO UPDATE SET offers_url = excluded.offers_url;
