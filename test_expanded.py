import json
import unittest
from unittest.mock import patch
import adapters
import catalog
import server

class ExpandedTests(unittest.TestCase):
    def test_catalog_all_sections_and_exclusions(self):
        text='# ► Audio Ripping\n## ▷ Download Sites\n* [One](https://one.org) - FLAC\n## ▷ Genre Specific Ripping\n* [Two](https://two.org) - FLAC\n## ▷ Telegram Bots\n* [Bot](https://t.me/bot) - FLAC\n# ► Media Soundtracks\n## ▷ Game Soundtracks\n* [Game](https://game.org) - MP3 / FLAC'
        records=catalog.inventory(text)
        self.assertEqual(len(records),4)
        self.assertEqual(len(catalog.source_list(records)),3)
        self.assertEqual(records[2]['disposition'],'excluded')
    def test_mirrors_and_cross_section_deduplication(self):
        records=catalog.inventory('## ▷ Streaming Sites\n* [A](https://a.org) - Music\n## ▷ Download Sites\n* [A](https://a.org) or [2](https://b.org) - FLAC')
        sources=catalog.source_list(records)
        self.assertEqual(len(sources),2)
        self.assertTrue(all(s['flac'] for s in sources))
    def test_lossless_not_ranked_by_alternate_mp3_bitrate(self):
        self.assertEqual(server.quality('FLAC MP3 320kbps')['rank'],server.quality('FLAC')['rank'])
    def test_password_form_is_not_submitted(self):
        with self.assertRaises(ValueError):server.search_form(server.Document('<form><input name="q"><input type="password"></form>').root,'https://example.org','q')
    def test_nonstandard_search_field(self):
        url,data=server.search_form(server.Document('<form action="/f"><input name="t" placeholder="Search"></form>').root,'https://example.org','Bach')
        self.assertEqual(url,'https://example.org/f?t=Bach')
    def test_challenge_detection_does_not_match_unused_captcha_script(self):
        self.assertFalse(server.is_challenge('<script src="recaptcha.js"></script><h1>Music</h1>'))
        self.assertTrue(server.is_challenge('<title>Just a moment</title>'))
    def test_api_preserves_unavailable_download_flag(self):
        data={'success':True,'data':{'tracks':{'items':[{'id':1,'title':'Song','performer':{'name':'Artist'},'maximum_bit_depth':24,'maximum_sampling_rate':96,'downloadable':False}],'total':1}}}
        fetch=lambda url:(json.dumps(data),url)
        response=adapters.search({'adapter':'arcod','id':'arcod.xyz','name':'ARCOD','url':'https://arcod.xyz'},'Artist',1,fetch,server.quality)
        self.assertEqual(len(response['results']),1)
        row=response['results'][0]
        self.assertFalse(row['availability'])
        self.assertTrue(row['metadataOnly'])
        self.assertEqual(row['quality']['bits'],24)
    def test_tidal_no_invented_resolution(self):
        fetch=lambda url:(json.dumps({'items':[{'id':1,'title':'Song','audioQuality':'LOSSLESS'}],'totalNumberOfItems':200}),url)
        response=adapters.search({'adapter':'tidal','id':'tidal-dl.pages.dev','name':'TIDAL DL','url':'https://tidal-dl.pages.dev'},'Song',5,fetch,server.quality)
        self.assertTrue(response['limited'])
        self.assertEqual(response['results'][0]['quality']['bits'],0)
    def test_khinsider_ignores_recommendations(self):
        with patch.object(server,'fetch',return_value=('<table id="songlist"><tr><th>Song</th><th>MP3</th></tr></table><aside>FLAC</aside>','')):
            self.assertFalse(server.detail('https://downloads.khinsider.com/game-soundtracks/album/test')['quality']['lossless'])

if __name__=='__main__':unittest.main()
