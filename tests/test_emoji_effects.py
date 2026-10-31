"""Browser regressions: python3 -m unittest discover -s tests -v.

Requires Python Playwright and Chromium (CHROMIUM_PATH overrides the executable).
Model output is injected through GFX._test; no camera, OBS or CDN is required.
"""
import functools
import http.server
import os
from pathlib import Path
import threading
import unittest

from playwright.sync_api import sync_playwright


class EmojiEffectsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(
            http.server.SimpleHTTPRequestHandler,
            directory=str(Path(__file__).resolve().parents[1]),
        )
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            executable_path=os.environ.get('CHROMIUM_PATH', '/usr/bin/chromium'),
            headless=True,
            args=['--no-sandbox'],
        )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.page = self.browser.new_page(viewport={'width': 1280, 'height': 720})
        self.addCleanup(self.page.close)
        # Advance particles ourselves, so frame rate and wall time cannot affect assertions.
        self.page.add_init_script('window.requestAnimationFrame = () => 0')
        self.page.route('https://**/*', lambda route: route.abort())
        self.page.goto(f'http://127.0.0.1:{self.server.server_port}/gesture-fx.html')
        self.page.wait_for_function('!!window.GFX')

    def test_rain_draws_at_moving_particle_positions(self):
        result = self.page.evaluate('''() => {
          GFX.fire('emojiRain', {count:45, duration:2.5});
          const particles=GFX._test.fx;
          const initial=particles.map(p=>({x:p.x,y:p.y}));
          for(let i=0;i<210;i++) for(const p of particles) p.update(1/60);
          const ctx=document.querySelector('#stage').getContext('2d');
          const transforms=[];
          const fillText=ctx.fillText;
          ctx.fillText=function(...args){
            const m=this.getTransform(); transforms.push({x:m.e,y:m.f});
            return fillText.apply(this,args);
          };
          try { for(const p of particles) p.draw(); }
          finally { ctx.fillText=fillText; }
          return particles.map((p,i)=>({x:p.x,y:p.y,start:initial[i],draw:transforms[i]}));
        }''')
        self.assertEqual(len(result), 45)
        self.assertGreater(max(p['x'] for p in result)-min(p['x'] for p in result), 500)
        for particle in result:
            self.assertGreater(particle['y'], particle['start']['y'])
            # Canvas transforms may round coordinates to single precision.
            self.assertAlmostEqual(particle['draw']['x'], particle['x'], delta=0.001)
            self.assertAlmostEqual(particle['draw']['y'], particle['y'], delta=0.001)

    def test_thumb_down_fires_rain_after_hold_once(self):
        result = self.page.evaluate('''() => {
          const t=GFX._test, rule=GFX.cfg().rules.find(r=>r.gesture==='Thumb_Down');
          rule.sound='none';
          const lm=Array.from({length:21},(_,i)=>({x:0.4+(i%4)*0.025,y:0.7-Math.floor(i/4)*0.06,z:0}));
          const frame={landmarks:[lm],handedness:[[{categoryName:'Right'}]],gestures:[[{categoryName:'Thumb_Down',score:0.99}]]};
          const count=()=>t.log.filter(x=>x.gesture==='Thumb_Down').length;
          t.frame(frame,1000); t.frame(frame,1000+rule.hold-1);
          const before=count();
          t.frame(frame,1000+rule.hold);
          const fired=count(), particles=t.fx.filter(p=>p.kind==='emoji').length;
          t.frame(frame,1000+rule.hold+rule.cooldown+100);
          return {before,fired,held:count(),particles,effect:t.log.find(x=>x.gesture==='Thumb_Down')?.effect};
        }''')
        self.assertEqual(result, {'before': 0, 'fired': 1, 'held': 1, 'particles': 45, 'effect': 'emojiRain'})


if __name__ == '__main__':
    unittest.main()
