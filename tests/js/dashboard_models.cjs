// Run the dashboard's shipped scripts against an in-memory DOM and intercepted fetch.
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {resolve} = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = readFileSync(resolve(__dirname, '../../src/axiom/web/index.html'), 'utf8');
const QWEN = 'qwen/qwen3.8-27b';
const SUPER_VL = 'nvidia/nemotron-3.5-super-vl:free';
const ULTRA = 'nvidia/nemotron-3-ultra-550b-a55b:free';

class Element {
    constructor(tag, attributes = '', owner = null) {
        this.tag = tag;
        this.owner = owner;
        this.attributes = new Map();
        for (const [,name,value] of attributes.matchAll(/(?:^|\s)([\w:-]+)(?:="([^"]*)")?/g)) {
            this.attributes.set(name, value ?? '');
        }
        this.value = '';
        this.children = [];
        this.hidden = this.attributes.has('hidden');
        this.disabled = this.attributes.has('disabled');
        this.open = this.attributes.has('open');
        this.inert = this.attributes.has('inert');
        this.listeners = {};
        this.style = {};
        const tokens = () => new Set(this.className.split(/\s+/).filter(Boolean));
        this.classList = {
            contains: token => tokens().has(token),
            add: (...names) => { this.className = [...new Set([...tokens(), ...names])].join(' '); },
            remove: (...names) => { this.className = [...tokens()].filter(n => !names.includes(n)).join(' '); },
            toggle: (name, force = !tokens().has(name)) => {
                if (force) this.classList.add(name);
                else this.classList.remove(name);
                return force;
            },
        };
    }
    setAttribute(name, value) { this.attributes.set(name, String(value)); }
    getAttribute(name) { return this.attributes.get(name) ?? null; }
    removeAttribute(name) { this.attributes.delete(name); }
    get className() { return this.getAttribute('class') || ''; }
    set className(value) { this.setAttribute('class', value); }
    focus() { if (this.owner) this.owner.activeElement = this; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    addEventListener(type, handler) { this.listeners[type] = handler; }
    change(value) {
        assert.equal(this.disabled, false);
        assert.ok(this.children.some(option => option.value === value), `Missing option ${value}`);
        this.value = value;
        this.listeners.change?.();
    }
}

function dashboard(askResponse = null, route = null, mobile = false, apiBase = '') {
    const elements = new Map();
    const document = {
        listeners: {},
        activeElement: null,
        addEventListener(type, listener) { this.listeners[type] = listener; },
        getElementById: id => elements.get(id) || null,
        createElement: tag => new Element(tag, '', document),
    };
    document.body = document.createElement('body');
    const window = {
        listeners: {},
        AXIOM_API_BASE: apiBase,
        matchMedia: () => ({matches: mobile}),
        addEventListener(type, listener) { this.listeners[type] = listener; },
    };
    for (const [, tag, attributes] of html.matchAll(/<([a-z][\w-]*)\b([^>]*)>/gi)) {
        const id = /\bid="([^"]+)"/.exec(attributes)?.[1];
        if (id) elements.set(id, new Element(tag, attributes, document));
    }
    // Initialize static select values from the real markup, including the default provider.
    for (const [, attributes, body] of html.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/gi)) {
        const select = elements.get(/\bid="([^"]+)"/.exec(attributes)?.[1]);
        if (!select) continue;
        for (const [, optionAttrs, text] of body.matchAll(/<option\b([^>]*)>([^<]*)<\/option>/gi)) {
            const value = /\bvalue="([^"]*)"/.exec(optionAttrs)?.[1] ?? text;
            select.append({value, textContent: text, selected: /\bselected\b/.test(optionAttrs)});
        }
        select.value = (select.children.findLast(option => option.selected) ?? select.children[0])?.value || '';
    }
    const get = id => elements.get(id) || null;
    const requests = [];
    const allRequests = [];
    async function fetch(path, options) {
        const pathname = path.replace(/^https?:\/\/[^/]+/, '');
        allRequests.push({path, options, pathname});
        if (pathname === '/api/status' || pathname === '/api/conditions') return new Promise(() => {});
        if (route) {
            const result = await route(path, options);
            if (result !== undefined) return {ok: true, json: async () => result};
        }
        if (pathname.startsWith('/api/runs?')) return {ok: true, json: async () => ({runs: [], total: 0})};
        if (pathname.startsWith('/api/comparisons?')) return {ok: true, json: async () => ({comparisons: [], total: 0})};
        assert.equal(pathname, '/api/ask');
        assert.equal(options.method, 'POST');
        requests.push(JSON.parse(options.body));
        return askResponse ? {ok: true, json: async () => askResponse} : {ok: false, json: async () => ({error: 'Test intercepted request'})};
    }
    const context = vm.createContext({document, window, fetch, URL});
    for (const [, script] of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) {
        vm.runInContext(script, context, {filename: 'dashboard-inline.js'});
    }
    return {get, document, allRequests, resize(narrow) {
        mobile = narrow;
        window.listeners.resize?.();
    }, send: async (expectedRequests = 1) => {
        const count = requests.length;
        await get('form').onsubmit({preventDefault() {}});
        assert.equal(requests.length, count + expectedRequests, 'Unexpected form request count');
        return requests.at(-1);
    }};
}

test('Groq displays Qwen on load and sends the visible model', async () => {
    const {get, send} = dashboard();
    assert.equal(get('provider').value, 'groq');
    assert.equal(get('model').tag, 'select');
    assert.equal(get('model').value, QWEN);
    assert.match(get('model').children.find(option => option.value === QWEN).textContent, /Qwen 3\.8 27B/);
    assert.equal(get('custom-model-control').hidden, true);
    const request = await send();
    assert.equal(request.provider, 'groq');
    assert.equal(request.model, QWEN);
});

const flush = () => new Promise(resolve => setImmediate(resolve));
const renderedText = node => [node.textContent || '', ...(node.children || []).map(renderedText)].join(' ');

test('saved demonstrations open through GET only and clearly label the replay', async () => {
    const saved = {run_id:'demo-fixture',system:'ignis',question:'Synthetic saved question?',answer:'Saved fixture answer.',claims:[],evidence:[]};
    const {get, allRequests} = dashboard(null, async path => {
        if (path === '/api/demos') return {demos:[{id:'source-answer',title:'Source-backed answer',description:'Synthetic recorded example.'}]};
        if (path === '/api/demos/source-answer') return {demo:{description:'Synthetic recorded example.'},run:saved,notice:'No new model request.'};
    });
    assert.equal(allRequests.some(r => r.path === '/api/demos'), false);
    await get('nav-demos').onclick();
    await flush();
    assert.equal(get('demos-view').hidden, false);
    assert.equal(get('research-view').hidden, true);
    const card = get('demo-list').children[0];
    await card.children.at(-1).onclick();
    assert.equal(get('answer').textContent, saved.answer);
    assert.match(get('status').textContent, /replay.*no new model request/);
    assert.equal(get('research-view').hidden, false);
    assert.equal(allRequests.filter(r => r.options?.method === 'POST').length, 0);
});

test('saved demo errors remain visible without starting a model request', async () => {
    const {get, allRequests} = dashboard(null, async path => {
        if (path === '/api/demos') throw new Error('Synthetic missing demonstration');
    });
    await get('nav-demos').onclick();
    await flush();
    assert.match(get('demo-error').textContent, /missing demonstration/);
    assert.equal(allRequests.filter(r => r.options?.method === 'POST').length, 0);
});

test('explicit source context is labeled and the pinned archive link has no PDF fragment', async () => {
    const archive='https://web.archive.org/web/20250712202704id_/https://blogs.nasa.gov/ISS_Science_Blog/2013/11/25/cool-flames-on-the-international-space-station-an-anatomy-of-discovery/';
    const response={question:'Synthetic question',system:'ignis',answer:'Synthetic context-only response',abstained:true,
        claims:[],draft_checks:[],evidence:[{source_id:'archive',chunk_id:'p1',title:'Archived source',experiment:'FLEX',
        url:'https://blogs.nasa.gov/original',document_url:archive,locator:'Article, 2013-11-25',text:'Synthetic archived text.',
        evidence_tier:3,selection_role:'explicit_source_scope'}]};
    const {get,send}=dashboard(response);
    await send();
    const card=get('evidence').children[0];
    assert.match(renderedText(card),/Requested source context/);
    assert.match(renderedText(card),/scientific support are not established/);
    assert.equal(card.children.find(node=>node.tag==='a').href,archive);
});

test('saved answers reopen with only GET and retain legacy missing fields', async () => {
    const original = {run_id:'legacy', answer:'Saved fixture answer.',claims:[{text:'Older claim without check metadata.'}]};
    const {get, allRequests} = dashboard(null, async path => {
        if (path.startsWith('/api/runs?')) return {runs:[{run_id:'legacy',question:'Saved answer',created_at:null}],total:1};
        if (path === '/api/runs/legacy') return original;
    });
    await flush();
    assert.match(renderedText(get('history-list')), /Date unavailable/);
    await get('history-list').children[0].children.at(-1).onclick();
    assert.equal(get('answer').textContent, original.answer);
    assert.equal(get('view-question').textContent, 'Saved answer');
    assert.equal(get('export').hidden, false);
    assert.equal(allRequests.filter(r => r.options?.method === 'POST').length, 0);
});

test('history search resets pages and older requests the next bounded page', async () => {
    const {get,allRequests} = dashboard(null, async path => {
        if (path.startsWith('/api/runs?')) return {runs:[{run_id:'fixture',question:'Fixture'}],total:10};
    });
    await flush();
    assert.equal(get('history-older').disabled,false);
    get('history-older').onclick();
    await flush();
    assert.ok(allRequests.some(r => r.path.includes('/api/runs?limit=8&offset=8')));
    get('history-search').value = 'a & b';
    get('history-search').listeners.keydown({key:'Enter',preventDefault(){}});
    await flush();
    assert.ok(allRequests.some(r => r.path === '/api/runs?limit=8&offset=0&q=a%20%26%20b'));
});

test('comparison uses selected model, fresh option and retains a failed side', async () => {
    const pair = {comparison_id:'pair',question:'Fixture question?',status:'partial',
        controls:{provider:'groq',model:QWEN,fresh:true},errors:{baseline:'Synthetic provider failure.'},
        baseline:{run_id:'baseline',system:'baseline',answer:'',error:'Synthetic provider failure.'},
        ignis:{run_id:'ignis',question:'Fixture question?',system:'ignis',answer:'Retained AXIOM answer.',claims:[],draft_checks:[],model_calls:[{cache_hit:true}]}};
    let request;
    const {get} = dashboard(null, async (path,options) => {
        if (path === '/api/compare') {request = JSON.parse(options.body); return pair;}
    });
    get('question').value = pair.question;
    get('compare-fresh').checked = true;
    await get('compare').onclick();
    assert.equal(request.model,QWEN);
    assert.equal(request.fresh,true);
    assert.equal(get('comparison-panel').hidden,false);
    assert.match(get('comparison-status').textContent,/Synthetic provider failure/);
    assert.match(renderedText(get('comparison-ignis')),/Retained AXIOM answer/);
    assert.match(renderedText(get('comparison-ignis')),/1 cached model replies reused/);
    await get('comparison-ignis').children[0].children.at(-1).onclick();
    assert.equal(get('answer').textContent,pair.ignis.answer);
    assert.equal(get('compare').disabled,false);
});

test('extractive comparison explains the missing model without sending POST', async () => {
    const {get,allRequests}=dashboard();
    get('question').value='Fixture question?';
    get('provider').change('extractive');
    await get('compare').onclick();
    assert.match(get('error').textContent,/Choose a model provider/);
    assert.equal(allRequests.filter(r=>r.options?.method==='POST').length,0);
});

test('OpenRouter defaults to Super VL and submits Ultra when selected', async () => {
    const {get, send} = dashboard();
    get('provider').change('openrouter');
    assert.equal(get('model').value, SUPER_VL);
    assert.equal(get('model').children.some(option => option.value === QWEN), false);
    assert.equal((await send()).model, SUPER_VL);
    get('model').change(ULTRA);
    const request = await send();
    assert.equal(request.provider, 'openrouter');
    assert.equal(request.model, ULTRA);
});

test('custom models send their trimmed ID and a provider switch clears stale input', async () => {
    const {get, send} = dashboard();
    get('model').change('__custom__');
    assert.equal(get('custom-model-control').hidden, false);
    assert.equal(get('custom-model').required, true);
    get('custom-model').value = '  fixture-model-id  ';
    assert.equal((await send()).model, 'fixture-model-id');
    get('provider').change('ollama');
    assert.equal(get('model').value, 'llama3.2:latest');
    assert.equal(get('custom-model-control').hidden, true);
    assert.equal(get('custom-model').required, false);
    assert.equal(get('custom-model').value, '');
    const request = await send();
    assert.equal(request.provider, 'ollama');
    assert.equal(request.model, 'llama3.2:latest');
});

test('extractive disables model selection, sends null and restores the provider default', async () => {
    const {get, send} = dashboard();
    get('provider').change('openrouter');
    get('model').change(ULTRA);
    get('provider').change('extractive');
    assert.equal(get('model').disabled, true);
    const request = await send();
    assert.equal(request.provider, 'extractive');
    assert.equal(request.model, null);
    get('provider').change('groq');
    assert.equal(get('model').disabled, false);
    assert.equal(get('model').value, QWEN);
});

test('blank custom model shows an error without sending a request', async () => {
    const {get, send} = dashboard();
    get('model').change('__custom__');
    get('custom-model').value = '   ';
    await send(0);
    assert.match(get('error').textContent, /Enter a model ID/);
    assert.equal(get('submit').disabled, false);
});

test('claim evidence and scope hints render from a successful response', async () => {
    const response = {
        answer: 'Fixture answer', mode: 'model', system: 'ignis', latency_ms: 5,
        abstained: false, provisional: true,
        steps: [{label:'Check claims',detail:'Fixture check'}],
        draft_checks: [{text:'Fixture claim',verdict:'needs_review',evidence_status:'partial',
            issues:['conflicting_or_limiting_evidence'],next_evidence:['Compare the test scopes.'],citations:[],
            semantic_review:{reason:'Fixture reason',uncertainty:'Fixture uncertainty'},
            evidence_checks:[{relation:'limits',quote:'Fixture limiting passage.',url:'https://ntrs.nasa.gov/citations/1',locator:'PDF page 2'}]}],
        source_cautions:[{field:'pressure_kpa',source_id:'fixture-source',values:[1,2]}],evidence:[]
    };
    const {get,send}=dashboard(response);
    await send();
    assert.equal(get('error').textContent,'');
    assert.equal(get('answer').textContent,'Fixture answer');
    const text = node => [node.textContent || '', ...(node.children || []).map(text)].join(' ');
    assert.match(text(get('claims')),/Passages checked by the model/);
    assert.match(text(get('claims')),/Fixture limiting passage/);
    assert.match(text(get('claims')),/partial/);
    assert.match(text(get('source-cautions')),/Source values that need a scope check/);
});

test('evaluation displays missing sources and ungraded progress without invented scores', async () => {
    const {get,allRequests}=dashboard(null,async path=>{
        if(path==='/api/benchmark')return {
            audit:{question_count:36,counts:{source_scope_available:10}},
            latest:{run_id:'pilot',provider:'groq',model:QWEN,split:'dev',report:{
                evaluation_kind:'exploratory_model_generation',
                progress:{overall:{completed:2,failed:1,pending:6,attempted:3,graded:0},by_system:{
                    ignis:{completed:1,failed:0,pending:2,blocked_scope:1}}},quality:{systems:{ignis:{graded_questions:0,claim_support:{value:null}}}}}}
        };
    });
    await flush();
    assert.match(get('evaluation-sources').textContent,/10 of 36/);
    assert.match(get('evaluation-status').textContent,/2 answers completed, 1 failed, 6 waiting/);
    assert.match(get('evaluation-quality').textContent,/scores are unavailable/);
    assert.doesNotMatch(renderedText(get('evaluation-progress')),/%|100/);
    assert.equal(allRequests.filter(r=>r.options?.method==='POST').length,0);
});

test('saved evaluation answers open in the existing inspector with GET only', async()=>{
    const run={question:'Saved evaluation question?',answer:'Saved evaluation answer.',claims:[]};
    const {get,allRequests}=dashboard(null,async path=>{
        if(path==='/api/benchmark')return {audit:{question_count:36,counts:{source_scope_available:10}},
            latest:{run_id:'pilot',provider:'groq',model:QWEN,split:'dev',report:{
                progress:{overall:{completed:1,failed:0,pending:0,attempted:1,graded:0},by_system:{}},quality:{systems:{}}}}};
        if(path==='/api/benchmark/pilot/answers')return {answers:[{question_id:'Q001',system:'ignis',prediction:{},run}]};
    });
    await flush();
    await get('evaluation-open').onclick();
    get('evaluation-answers').children[0].children.at(-1).onclick();
    assert.equal(get('answer').textContent,run.answer);
    assert.equal(get('view-question').textContent,run.question);
    assert.equal(allRequests.filter(r=>r.options?.method==='POST').length,0);
});

test('workspace navigation selects one visible page and moves keyboard focus without sending a query', () => {
    const {get, document, allRequests} = dashboard();
    const views = ['research', 'evaluation', 'library'];
    for (const selected of ['evaluation', 'library', 'research']) {
        get('nav-' + selected).onclick();
        for (const name of views) {
            assert.equal(get(name + '-view').hidden, name !== selected);
            assert.equal(get('nav-' + name).getAttribute('aria-current'), name === selected ? 'page' : null);
        }
        assert.equal(get('top-model-controls').hidden, selected !== 'research');
        assert.equal(document.activeElement, get('main-content'));
    }
    assert.equal(allRequests.filter(r => r.options?.method === 'POST').length, 0);
});

test('options button and native disclosure keep the expanded state in sync', () => {
    const {get} = dashboard();
    const toggle = get('options-toggle');
    const options = get('research-options');
    assert.equal(options.open, false);
    assert.equal(toggle.getAttribute('aria-expanded'), 'false');
    toggle.onclick();
    assert.equal(options.open, true);
    assert.equal(toggle.getAttribute('aria-expanded'), 'true');
    options.open = false;
    options.listeners.toggle();
    assert.equal(toggle.getAttribute('aria-expanded'), 'false');
});

test('mobile menu excludes background controls and Escape restores focus to its opener', () => {
    const {get, document} = dashboard(null, null, true);
    const sidebar = get('sidebar');
    const workspace = get('workspace');
    const toggle = get('sidebar-toggle');
    assert.equal(sidebar.inert, true);
    assert.equal(sidebar.getAttribute('aria-hidden'), 'true');
    toggle.onclick();
    assert.equal(sidebar.inert, false);
    assert.equal(sidebar.getAttribute('aria-hidden'), 'false');
    assert.equal(workspace.inert, true);
    assert.equal(toggle.getAttribute('aria-expanded'), 'true');
    assert.equal(document.body.style.overflow, 'hidden');
    assert.equal(document.activeElement, get('new-question'));
    document.listeners.keydown({key: 'Escape'});
    assert.equal(sidebar.inert, true);
    assert.equal(workspace.inert, false);
    assert.equal(toggle.getAttribute('aria-expanded'), 'false');
    assert.equal(document.body.style.overflow, '');
    assert.equal(document.activeElement, toggle);
});

test('crossing the mobile breakpoint synchronizes sidebar accessibility in both directions', () => {
    const {get, resize} = dashboard();
    assert.equal(get('sidebar').inert, false);
    resize(true);
    assert.equal(get('sidebar').inert, true);
    assert.equal(get('sidebar').getAttribute('aria-hidden'), 'true');
    get('sidebar-toggle').onclick();
    resize(false);
    assert.equal(get('sidebar').inert, false);
    assert.equal(get('workspace').inert, false);
    assert.equal(get('sidebar-toggle').getAttribute('aria-expanded'), 'false');
    assert.equal(get('app-shell').classList.contains('sidebar-open'), false);
});

test('new research preserves the model and ignores the answer from an earlier pending request', async () => {
    let releaseAsk;
    const {get, document} = dashboard(null, path => {
        if (path === '/api/ask') return new Promise(resolve => { releaseAsk = resolve; });
    });
    get('provider').change('openrouter');
    get('model').change(ULTRA);
    get('question').value = 'Earlier request';
    const earlier = get('form').onsubmit({preventDefault() {}});
    assert.equal(get('form').getAttribute('aria-busy'), 'true');
    assert.equal(get('result-panel').hidden, false);
    get('new-question').onclick();
    assert.equal(get('welcome').hidden, false);
    assert.equal(get('result-panel').hidden, true);
    assert.equal(document.activeElement, get('question'));
    assert.equal(get('question').value, '');
    get('question').value = 'My next question';
    releaseAsk({question: 'Earlier request', answer: 'Outdated result', claims: []});
    await earlier;
    assert.equal(get('form').getAttribute('aria-busy'), 'false');
    assert.equal(get('submit').disabled, false);
    assert.equal(get('question').value, 'My next question');
    assert.equal(get('provider').value, 'openrouter');
    assert.equal(get('model').value, ULTRA);
    assert.equal(get('welcome').hidden, false);
    assert.equal(get('result-panel').hidden, true);
    assert.equal(get('comparison-panel').hidden, true);
    assert.equal(get('export').hidden, true);
    assert.doesNotMatch(get('answer').textContent || '', /Outdated result/);
    assert.doesNotMatch(get('error').textContent || '', /earlier request is finishing/i);
});

test('appearance control updates the workspace theme and its accessible action label', () => {
    const {get} = dashboard();
    const toggle = get('theme-toggle');
    const shell = get('app-shell');
    for (const dark of [true, false]) {
        toggle.onclick();
        assert.equal(shell.classList.contains('dark'), dark);
        assert.match(toggle.getAttribute('aria-label'), dark ? /switch to light/i : /switch to dark/i);
        assert.match(get('theme-label').textContent, dark ? /light/i : /dark/i);
    }
});

test('Enter submits one question while Shift+Enter and IME composition preserve editing', async () => {
    const {get, allRequests} = dashboard();
    const question = get('question');
    question.value = 'Keyboard input';
    let submitted;
    get('form').requestSubmit = () => { submitted = get('form').onsubmit({preventDefault() {}}); };
    function enter(modifiers) {
        let prevented = false;
        question.listeners.keydown({key: 'Enter', ...modifiers, preventDefault() { prevented = true; }});
        return prevented;
    }
    assert.equal(enter({shiftKey: true}), false);
    assert.equal(enter({isComposing: true}), false);
    assert.equal(submitted, undefined);
    assert.equal(enter({}), true);
    assert.ok(submitted);
    await submitted;
    assert.equal(allRequests.filter(r => r.path === '/api/ask' && r.options?.method === 'POST').length, 1);
});

test('Ask sends the submitted question once and leaves the composer ready for another', async () => {
    const original = 'Which fuel did the experiment use?';
    let finish;
    const {get, allRequests} = dashboard(null, path => {
        if (path === '/api/ask') return new Promise(resolve => { finish = resolve; });
    });
    get('question').value = original;
    const submit = () => get('form').onsubmit({preventDefault() {}});
    const first = submit();
    const second = submit();
    const asks = allRequests.filter(r => r.path === '/api/ask');
    assert.equal(asks.length, 1);
    assert.equal(JSON.parse(asks[0].options.body).question, original);
    assert.equal(get('question').value, '');
    assert.equal(get('view-question').textContent, original);
    finish({question: original, answer: 'Fixture answer', claims: []});
    await Promise.all([first, second]);
    assert.equal(get('answer').textContent, 'Fixture answer');
    assert.equal(get('view-question').textContent, original);
    assert.equal(get('question').value, '');
});

test('a failed Ask restores the submitted question for another attempt', async () => {
    const {get} = dashboard();
    const original = 'What was the test atmosphere?';
    get('question').value = original;
    const pending = get('form').onsubmit({preventDefault() {}});
    assert.equal(get('question').value, '');
    await pending;
    assert.match(get('error').textContent, /Test intercepted request/);
    assert.equal(get('question').value, original);
    assert.equal(get('submit').disabled, false);
});

test('opening a saved comparison keeps it visible when an earlier Ask completes', async () => {
    const pair = {comparison_id:'pair', question:'Saved pair question', status:'complete',
        baseline:{answer:'Saved baseline'}, ignis:{answer:'Saved AXIOM'}};
    let finish;
    const {get} = dashboard(null, path => {
        if (path.startsWith('/api/comparisons?')) return {comparisons: [pair], total: 1};
        if (path === '/api/comparisons/pair') return pair;
        if (path === '/api/ask') return new Promise(resolve => { finish = resolve; });
    });
    await flush();
    get('question').value = 'Earlier question';
    const earlier = get('form').onsubmit({preventDefault() {}});
    const open = get('comparisons-list').children[0].children.at(-1);
    assert.match(open.getAttribute('aria-label'), /Open comparison: Saved pair question/);
    await open.onclick();
    assert.equal(get('comparison-panel').hidden, false);
    finish({question:'Earlier question', answer:'Late answer', claims:[]});
    await earlier;
    assert.equal(get('comparison-panel').hidden, false);
    assert.equal(get('result-panel').hidden, true);
    assert.match(renderedText(get('comparison-ignis')), /Saved AXIOM/);
    assert.doesNotMatch(get('answer').textContent || '', /Late answer/);
});


// Evaluation fixtures describe fictional outputs, never combustion judgments.
function impactFixture(runId='pilot') {
    const status=(answered,claims)=>({status:'completed',answered,abstained:!answered,claims});
    return {
        schema_version:'benchmark-impact-v1',run_id:runId,integrity_verified:true,
        progress:{scheduled:9,completed:8,failed:1,pending:0},
        systems:[
            {system:'baseline',scheduled:3,completed:3,answered:1,abstained:2,failed:0,pending:0},
            {system:'rag_only',scheduled:3,completed:3,answered:2,abstained:1,failed:0,pending:0},
            {system:'ignis',scheduled:3,completed:2,answered:1,abstained:1,failed:1,pending:0}],
        critic:{available:true,matched_pairs:2,scheduled_pairs:3,excluded_pairs:1,
            raw_draft_claims:5,writer_withheld_claims:3,rag_output_claims:2,ignis_output_claims:1,
            additional_withheld_claims:1,additional_withheld_rate:{numerator:1,denominator:2,value:.5},
            answer_transitions:[{source:'answered',target:'answered',count:1},{source:'abstained',target:'abstained',count:1}],
            reasons:[{id:'numeric',label:'Numeric value or unit check',claims:1,question_ids:['Q001']}]},
        questions:[
            {question_id:'Q001',question:'Synthetic changed question?',pair_status:'matched',rag_output_claims:2,ignis_output_claims:1,additional_withheld_claims:1,
                systems:{baseline:status(false,0),rag_only:status(true,2),ignis:status(true,1)}},
            {question_id:'Q002',question:'Synthetic writer already withheld?',pair_status:'matched',rag_output_claims:0,ignis_output_claims:0,additional_withheld_claims:0,
                systems:{baseline:status(false,0),rag_only:status(false,0),ignis:status(false,0)}},
            {question_id:'Q003',question:'Synthetic provider failure?',pair_status:'excluded',additional_withheld_claims:null,
                systems:{baseline:status(true,1),rag_only:status(true,1),ignis:{status:'failed',answered:null,abstained:null,claims:null}}}],
        provider:{cache_hits:4,fresh_successes:2},scientific_quality:{status:'ungraded',independent_grades:0,accuracy:null}
    };
}

function impactOverview(runId='pilot') {
    return {audit:{question_count:3,counts:{source_scope_available:3}},latest:{run_id:runId,provider:'groq',model:QWEN,split:'all',report:{
        progress:{overall:{completed:8,failed:1,pending:0,attempted:9,graded:0},by_system:{ignis:{completed:2,failed:1,pending:0}}},quality:{systems:{}}}}};
}

test('impact charts use released RAG claims and keep scientific quality ungraded',async()=>{
    const {get,allRequests}=dashboard(null,path=>{
        if(path==='/api/benchmark') return impactOverview();
        if(path==='/api/benchmark/pilot/impact') return impactFixture();
    });
    await flush();
    assert.equal(get('impact-error').textContent,'');
    assert.equal(get('impact-dashboard').hidden,false);
    assert.equal(get('impact-rag-count').textContent,'2');
    assert.equal(get('impact-ignis-count').textContent,'1');
    assert.match(renderedText(get('impact-key-results')),/50\.0%/);
    assert.match(get('impact-method-note').textContent,/5 raw draft claims included 3 already withheld/);
    assert.match(get('evaluation-quality').textContent,/not errors prevented/);
    assert.match(renderedText(get('impact-outcome-bars')),/1 failed/);
    assert.equal(allRequests.filter(row=>row.options?.method==='POST').length,0);
});

test('impact chart filters drill into changed, failed and reason-specific cases',async()=>{
    const {get}=dashboard(null,path=>{
        if(path==='/api/benchmark') return impactOverview();
        if(path==='/api/benchmark/pilot/impact') return impactFixture();
    });
    await flush();
    assert.equal(get('impact-question-grid').children.length,3);
    get('impact-filter-changed').onclick();
    assert.equal(get('impact-question-grid').children.length,1);
    assert.match(renderedText(get('impact-question-grid')),/Q001/);
    get('impact-filter-failed').onclick();
    assert.equal(get('impact-question-grid').children.length,1);
    assert.match(renderedText(get('impact-question-grid')),/Q003/);
    assert.match(renderedText(get('impact-question-grid')),/Failed/);
    get('impact-reason-bars').children[0].onclick();
    assert.match(get('impact-filter-note').textContent,/Numeric value/);
    assert.match(renderedText(get('impact-question-grid')),/Q001/);
    get('impact-filter-all').onclick();
    assert.equal(get('impact-question-grid').children.length,3);
});

test('impact cases open saved claims, flags and sources with one cached GET and no inference',async()=>{
    const cite={source_id:'synthetic-source',chunk_id:'synthetic-chunk',quote:'Synthetic observation with sufficient quotation context.',url:'https://ntrs.nasa.gov/citations/1',locator:'Synthetic passage'};
    const a={text:'Synthetic retained statement.',citations:[cite],verdict:'model_supported_needs_review',issues:[]};
    const b={text:'Synthetic withheld numeric statement.',citations:[cite],verdict:'needs_review',issues:['numeric_unit_unresolved']};
    const rows=[
        {question_id:'Q001',system:'rag_only',prediction:{claims:[a,b],abstained:false},run:{question:'Synthetic changed question?',answer:'Synthetic writer answer.',claims:[a,b]}},
        {question_id:'Q001',system:'ignis',prediction:{claims:[a],abstained:false},run:{question:'Synthetic changed question?',answer:'Synthetic checked answer.',claims:[a],draft_checks:[a,b]}}];
    const {get,allRequests}=dashboard(null,path=>{
        if(path==='/api/benchmark') return impactOverview();
        if(path==='/api/benchmark/pilot/impact') return impactFixture();
        if(path==='/api/benchmark/pilot/answers') return {answers:rows};
    });
    await flush();
    await get('impact-question-grid').children[0].onclick();
    assert.equal(get('impact-detail').hidden,false);
    assert.match(renderedText(get('impact-detail-content')),/Additionally withheld by safety checks/);
    assert.match(renderedText(get('impact-detail-content')),/measurement unit needs review/);
    assert.match(renderedText(get('impact-detail-content')),/Cited evidence/);
    assert.match(get('impact-detail-status').textContent,/2 RAG claims → 1/);
    await get('evaluation-open').onclick();
    assert.equal(allRequests.filter(row=>row.path.endsWith('/answers')).length,1);
    assert.equal(allRequests.filter(row=>row.options?.method==='POST').length,0);
});

test('an older impact response cannot overwrite a refreshed run',async()=>{
    let finishOld, overviewCalls=0;
    const {get}=dashboard(null,path=>{
        if(path==='/api/benchmark') return impactOverview(++overviewCalls===1?'pilot':'new-run');
        if(path==='/api/benchmark/pilot/impact') return new Promise(resolve=>{finishOld=resolve;});
        if(path==='/api/benchmark/new-run/impact') return impactFixture('new-run');
    });
    await flush();
    await get('evaluation-refresh').onclick();
    finishOld(impactFixture());
    await flush();
    assert.equal(get('impact-dashboard').hidden,false);
    assert.match(get('impact-provider-note').textContent,/new-run/);
    assert.equal(get('impact-rag-count').textContent,'2');
});

test('unverified metrics fail closed instead of displaying successful-looking zeros',async()=>{
    const {get}=dashboard(null,path=>{
        if(path==='/api/benchmark') return impactOverview();
        if(path==='/api/benchmark/pilot/impact') return {...impactFixture(),integrity_verified:false};
    });
    await flush();
    assert.equal(get('impact-dashboard').hidden,true);
    assert.equal(get('impact-export').disabled,true);
    assert.match(get('impact-error').textContent,/could not be verified/);
    assert.match(get('evaluation-status').textContent,/8 answers completed, 1 failed/);
});

test('a configured API base prefixes every dashboard request',async()=>{
    const base='https://api.axiomcombustion.us/';
    const {allRequests}=dashboard(null,null,false,base);
    await flush();
    const paths=allRequests.map(request=>request.path);
    assert.ok(paths.includes(base.slice(0,-1)+'/api/status'),paths.join(', '));
    assert.ok(paths.includes(base.slice(0,-1)+'/api/conditions'),paths.join(', '));
    assert.ok(paths.every(path=>path.startsWith(base.slice(0,-1)+'/api/')),paths.join(', '));
    assert.ok(allRequests.every(request=>request.pathname.startsWith('/api/')),paths.join(', '));
});

test('no matched pairs leave impact unavailable rather than a zero-percent improvement',async()=>{
    const fixture=impactFixture();fixture.critic.available=false;fixture.critic.matched_pairs=0;fixture.critic.reasons=[];
    const {get}=dashboard(null,path=>{
        if(path==='/api/benchmark') return impactOverview();
        if(path==='/api/benchmark/pilot/impact') return fixture;
    });
    await flush();
    assert.equal(get('impact-rag-count').textContent,'—');
    assert.equal(get('impact-key-results').children.length,0);
    assert.match(get('impact-claim-caption').textContent,/No completed shared-draft pairs/);
});
