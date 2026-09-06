import unittest
from unittest.mock import patch
import server as s

class SearchTests(unittest.TestCase):
    def test_quality_order_and_unknown(self):
        self.assertGreater(s.quality('FLAC 24-bit 96 kHz')['rank'], s.quality('MP3 320kbps')['rank'])
        self.assertEqual(s.quality('M4A')['lossless'], False)
        self.assertEqual(s.quality('artist 2024')['rank'], [0,0,0,0])
        self.assertEqual(s.quality('FLAC 16 bit 44,1 kHz')['rate'], 44.1)
    def test_search_form(self):
        doc=s.Document('<form action="/search" method="post"><input type="hidden" name="do" value="search"><input name="story"></form>').root
        url,data=s.search_form(doc,'https://example.org','Би-2 & live')
        self.assertEqual(url,'https://example.org/search')
        self.assertEqual(s.U.parse_qs(data.decode())['story'],['Би-2 & live'])
    def test_no_quality_leak_and_no_navigation(self):
        doc=s.Document('<nav><a href="/tag/test">Test Album FLAC</a></nav><h2><a href="/release">Test Album</a></h2><aside>FLAC 24-bit 192 kHz</aside>').root
        rows=s.candidates(doc,'https://example.org','Test Album',{'id':'example.org','name':'Example'})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['quality']['rank'],[0,0,0,0])
    def test_catalog_boundaries(self):
        html='<h3>Download Sites</h3>'+''.join(f'<a href="https://s{i}.org">Site {i}</a>' for i in range(6))+'<h3>Other</h3><a href="https://other.org">Other</a>'
        self.assertEqual(len(s.parse_catalog(html)),6)
    def test_partial_results_survive_page_failure(self):
        source={'id':'example.org','name':'Example','url':'https://example.org'}
        responses=[('<form><input name="s"></form>','https://example.org'),('<h2><a href="/album">Test Album FLAC</a></h2><a href="/page/2" rel="next">Next</a>','https://example.org/?s=test')]
        with patch.object(s,'fetch',side_effect=responses+[TimeoutError('timeout')]):
            result=s.run_search(source,'Test Album',2)
        self.assertEqual(result['status'],'error')
        self.assertEqual(len(result['results']),1)
        self.assertTrue(result['limited'])
    def test_private_urls_blocked(self):
        with self.assertRaises(ValueError):s.public_url('http://127.0.0.1')
        with self.assertRaises(ValueError):s.public_url('file:///etc/passwd')
    def test_detail_excludes_sidebar(self):
        html='<aside>Format: FLAC 24-bit 192 kHz</aside><div class="entry-content">Format: MP3 Quality: 320Kbps Size: 50 MB</div>'
        with patch.object(s,'fetch',return_value=(html,'https://example.org')):
            result=s.detail('https://example.org')
        self.assertFalse(result['quality']['lossless'])
        self.assertEqual(result['quality']['kbps'],320)

if __name__=='__main__': unittest.main()
