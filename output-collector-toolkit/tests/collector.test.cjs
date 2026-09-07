const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const core = html.match(/<script id="collector-core">([\s\S]*?)<\/script>/)[1];
const Collector = vm.runInNewContext(core + '; Collector');
const schema = name => JSON.parse(html.match(new RegExp(`<script id="${name}-schema" type="application/json">(.*?)<\\/script>`))[1]);
const questionSchema = schema('question'), reviewSchema = schema('review');
const q = (text = '测试问题') => ({local_id:'Q001', user_input:text, user_profile:{stage:null,locale:'zh-CN',baby_age_days:30,background:[]}, source_ids:[],pair_key:null,changed_factor:null});
const r = () => ({case_id:'S01-Q001',safety:{candidate_class:'general_health',boundary_note:''},initial_assessment:'评估',possible_consultation_response:'候选回复',follow_ups:[]});

test('all browser scripts parse', () => {
  for (const m of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)) if (!m[1].includes('application/json')) new vm.Script(m[2]);
});

test('collect, pair, batch-copy, export, and restore preserve content', () => {
  const first = Collector.addQuestions(Collector.empty(), [q()], 'S01', questionSchema);
  assert.equal(first.added, 1);
  const state = Collector.addReviews(first.state, [r()], false, reviewSchema).state;
  assert.equal(Collector.stats(state).ready, 1);
  assert.equal(Collector.batchInput(state, 'S01').cases[0].case_id, 'S01-Q001');
  assert.match(Collector.csv(state).text, /draft_ready/);
  assert.equal(JSON.stringify(Collector.verifyBackup(state, questionSchema, reviewSchema)), JSON.stringify(state));
});

test('conflicting batches are atomic and duplicate records are skipped', () => {
  const state = Collector.addQuestions(Collector.empty(), [q()], 'S01', questionSchema).state;
  assert.equal(Collector.addQuestions(state, [q()], 'S01', questionSchema).skipped, 1);
  assert.throws(() => Collector.addQuestions(state, [{...q(),local_id:'Q002'},q('不同问题')], 'S01', questionSchema));
  assert.equal(state.questions.length, 1);
});

test('orphan reviews block CSV while missing reviews remain exportable', () => {
  const state = Collector.addQuestions(Collector.empty(), [q()], 'S01', questionSchema).state;
  assert.match(Collector.csv(state).text, /missing_review/);
  const orphan = Collector.addReviews(state, [{...r(),case_id:'S02-Q001'}], false, reviewSchema).state;
  assert.throws(() => Collector.csv(orphan), /未找到/);
});

test('CSV formula protection does not mutate backups or copied input', () => {
  const state = Collector.addQuestions(Collector.empty(), [q('=1+1')], 'S01', questionSchema).state;
  assert.match(Collector.csv(state).text, /'=1\+1/);
  assert.equal(Collector.batchInput(state).cases[0].user_input, '=1+1');
  assert.equal(state.questions[0].question.user_input, '=1+1');
});

test('fenced, wrapped and concatenated output remains supported', () => {
  const wrapped = JSON.stringify({input:{},output:JSON.stringify({questions:[q()]})});
  assert.equal(Collector.extract('```json\n' + wrapped + '\n```', 'questions').length, 1);
  assert.equal(Collector.extract(JSON.stringify(q()) + '\n' + JSON.stringify(q()), 'questions').length, 2);
  assert.throws(() => Collector.extract('{"questions":[', 'questions'), /没有结束/);
});
