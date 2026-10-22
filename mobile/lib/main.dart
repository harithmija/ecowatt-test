import 'dart:async';
import 'dart:math' as math;

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'api.dart';

const green = Color(0xFF0B4F3C);
const greenMid = Color(0xFF3E9B73);
const mint = Color(0xFF9BD3B5);
const gold = Color(0xFFC9A227);
const canvas = Color(0xFFF5FAF7);
const colors = [green, greenMid, mint, gold];

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final api = await EcoWattApi.create();
  runApp(
    ChangeNotifierProvider(
      create: (_) => AppState(api)..restoreSession(),
      child: const EcoWattApp(),
    ),
  );
}

class AppState extends ChangeNotifier {
  AppState(this.api) {
    api.onUnauthorized = () {
      if (_user != null) {
        _user = null;
        notifyListeners();
      }
    };
  }

  final EcoWattApi api;
  Map<String, dynamic>? _user;
  bool _starting = true;
  bool _busy = false;
  String? _error;

  Map<String, dynamic>? get user => _user;
  bool get starting => _starting;
  bool get busy => _busy;
  String? get error => _error;

  Future<void> restoreSession() async {
    try {
      final response = await api.getMap('/api/auth/me');
      final user = response['user'];
      _user = user is Map ? Map<String, dynamic>.from(user) : null;
    } on ApiException catch (error) {
      _error = error.message;
    } finally {
      _starting = false;
      notifyListeners();
    }
  }

  Future<bool> signIn(String email, String password) async {
    return _authenticate('/api/auth/login', {
      'email': email.trim(),
      'password': password,
    });
  }

  Future<bool> signUp(String name, String email, String password) async {
    return _authenticate('/api/auth/signup', {
      'name': name.trim(),
      'email': email.trim(),
      'password': password,
    });
  }

  Future<bool> _authenticate(String path, Map<String, dynamic> body) async {
    _busy = true;
    _error = null;
    notifyListeners();
    try {
      final response = await api.post(path, body: body);
      _user = Map<String, dynamic>.from(response['user'] as Map);
      return true;
    } on ApiException catch (error) {
      _error = error.message;
      return false;
    } finally {
      _busy = false;
      notifyListeners();
    }
  }

  Future<bool> signOut() async {
    _busy = true;
    _error = null;
    notifyListeners();
    try {
      await api.post('/api/auth/logout');
    } on ApiException catch (error) {
      _error = error.message;
      _busy = false;
      notifyListeners();
      return false;
    }
    await api.clearCookies();
    _user = null;
    _busy = false;
    _error = null;
    notifyListeners();
    return true;
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }
}

class EcoWattApp extends StatelessWidget {
  const EcoWattApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'EcoWatt AI',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: green),
        scaffoldBackgroundColor: canvas,
        appBarTheme: const AppBarTheme(
          backgroundColor: canvas,
          foregroundColor: green,
          centerTitle: false,
        ),
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: Colors.white,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: const BorderSide(color: Color(0xFFD5E5DC)),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: const BorderSide(color: Color(0xFFD5E5DC)),
          ),
        ),
      ),
      home: Consumer<AppState>(
        builder: (context, state, _) {
          if (state.starting) {
            return const Scaffold(
              body: Center(child: CircularProgressIndicator()),
            );
          }
          return state.user == null ? const AuthScreen() : const ResidentShell();
        },
      ),
    );
  }
}

class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _signup = false;
  bool _obscure = true;

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    final state = context.read<AppState>();
    final success = _signup
        ? await state.signUp(_name.text, _email.text, _password.text)
        : await state.signIn(_email.text, _password.text);
    if (!success && mounted && state.error != null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(state.error!)),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(Icons.bolt_rounded, size: 58, color: green),
                  const SizedBox(height: 12),
                  Text(
                    'EcoWatt AI',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.headlineMedium?.copyWith(
                          color: green,
                          fontWeight: FontWeight.bold,
                        ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    _signup ? 'Create your resident account' : 'Welcome back',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.bodyLarge,
                  ),
                  const SizedBox(height: 28),
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(20),
                      child: Form(
                        key: _formKey,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            if (_signup) ...[
                              TextFormField(
                                controller: _name,
                                textCapitalization: TextCapitalization.words,
                                decoration: const InputDecoration(
                                  labelText: 'Name',
                                  prefixIcon: Icon(Icons.person_outline),
                                ),
                                validator: (value) =>
                                    value == null || value.trim().isEmpty
                                        ? 'Enter your name'
                                        : null,
                              ),
                              const SizedBox(height: 14),
                            ],
                            TextFormField(
                              controller: _email,
                              keyboardType: TextInputType.emailAddress,
                              autofillHints: const [AutofillHints.email],
                              decoration: const InputDecoration(
                                labelText: 'Email',
                                prefixIcon: Icon(Icons.email_outlined),
                              ),
                              validator: (value) {
                                if (value == null ||
                                    !RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
                                        .hasMatch(value.trim())) {
                                  return 'Enter a valid email';
                                }
                                return null;
                              },
                            ),
                            const SizedBox(height: 14),
                            TextFormField(
                              controller: _password,
                              obscureText: _obscure,
                              autofillHints: [
                                _signup
                                    ? AutofillHints.newPassword
                                    : AutofillHints.password,
                              ],
                              decoration: InputDecoration(
                                labelText: 'Password',
                                helperText:
                                    _signup ? 'At least 12 characters' : null,
                                prefixIcon: const Icon(Icons.lock_outline),
                                suffixIcon: IconButton(
                                  onPressed: () =>
                                      setState(() => _obscure = !_obscure),
                                  icon: Icon(
                                    _obscure
                                        ? Icons.visibility_outlined
                                        : Icons.visibility_off_outlined,
                                  ),
                                ),
                              ),
                              validator: (value) {
                                if (value == null || value.length < 12) {
                                  return 'Use at least 12 characters';
                                }
                                return null;
                              },
                              onFieldSubmitted: (_) => _submit(),
                            ),
                            const SizedBox(height: 20),
                            FilledButton(
                              onPressed: state.busy ? null : _submit,
                              child: state.busy
                                  ? const SizedBox(
                                      width: 20,
                                      height: 20,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                      ),
                                    )
                                  : Text(_signup ? 'Create account' : 'Sign in'),
                            ),
                            const SizedBox(height: 8),
                            TextButton(
                              onPressed: state.busy
                                  ? null
                                  : () {
                                      state.clearError();
                                      setState(() => _signup = !_signup);
                                    },
                              child: Text(
                                _signup
                                    ? 'Already have an account? Sign in'
                                    : 'New to EcoWatt? Create an account',
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'Connect this app to your EcoWatt server. For a phone, use the computer’s LAN address or a deployed HTTPS URL.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.black54),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class ResidentShell extends StatefulWidget {
  const ResidentShell({super.key});

  @override
  State<ResidentShell> createState() => _ResidentShellState();
}

class _ResidentShellState extends State<ResidentShell> {
  int _index = 0;
  static const _titles = [
    'Overview',
    'Monthly report',
    'Appliances',
    'AI advisor',
    'Savings simulator',
    'Sustainability',
  ];

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AppState>().user ?? {};
    final pages = [
      const OverviewPage(),
      const MonthlyPage(),
      const AppliancesPage(),
      const AdvisorPage(),
      const SimulatorPage(),
      const SustainabilityPage(),
    ];
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(_titles[_index]),
            if (user['name'] is String)
              Text(
                user['name'] as String,
                style: Theme.of(context).textTheme.labelSmall,
              ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            onPressed: () async {
              final state = context.read<AppState>();
              final success = await state.signOut();
              if (!success && context.mounted && state.error != null) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text(state.error!)),
                );
              }
            },
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: IndexedStack(index: _index, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (index) => setState(() => _index = index),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.space_dashboard_outlined),
            selectedIcon: Icon(Icons.space_dashboard),
            label: 'Home',
          ),
          NavigationDestination(
            icon: Icon(Icons.calendar_month_outlined),
            label: 'Monthly',
          ),
          NavigationDestination(
            icon: Icon(Icons.electrical_services_outlined),
            label: 'Appliances',
          ),
          NavigationDestination(
            icon: Icon(Icons.chat_bubble_outline),
            label: 'Advisor',
          ),
          NavigationDestination(
            icon: Icon(Icons.savings_outlined),
            label: 'Savings',
          ),
          NavigationDestination(
            icon: Icon(Icons.eco_outlined),
            label: 'Impact',
          ),
        ],
      ),
    );
  }
}

class ApiPage<T> extends StatefulWidget {
  const ApiPage({required this.load, required this.builder, super.key});

  final Future<T> Function() load;
  final Widget Function(BuildContext context, T data) builder;

  @override
  State<ApiPage<T>> createState() => _ApiPageState<T>();
}

class _ApiPageState<T> extends State<ApiPage<T>> {
  late Future<T> _future;

  @override
  void initState() {
    super.initState();
    _future = widget.load();
  }

  Future<void> _reload() async {
    final next = widget.load();
    setState(() => _future = next);
    try {
      await next;
    } on Object {
      // FutureBuilder displays the error state after the refresh completes.
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<T>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return ErrorPanel(error: snapshot.error!, retry: _reload);
        }
        return RefreshIndicator(
          onRefresh: () async => _reload(),
          child: widget.builder(context, snapshot.data as T),
        );
      },
    );
  }
}

class ErrorPanel extends StatelessWidget {
  const ErrorPanel({required this.error, required this.retry, super.key});

  final Object error;
  final VoidCallback retry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off_outlined, size: 42, color: green),
            const SizedBox(height: 12),
            Text(error.toString(), textAlign: TextAlign.center),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              onPressed: retry,
              icon: const Icon(Icons.refresh),
              label: const Text('Try again'),
            ),
          ],
        ),
      ),
    );
  }
}

class OverviewPage extends StatelessWidget {
  const OverviewPage({super.key});

  @override
  Widget build(BuildContext context) {
    final api = context.read<AppState>().api;
    return ApiPage<Map<String, dynamic>>(
      load: () => api.getMap('/api/overview'),
      builder: (context, data) {
        final appliances = _map(data['by_appliance']);
        final trend = _map(data['trend']);
        final series = _map(trend['series']);
        final dates = _list(trend['dates']);
        final alerts = _list(data['alerts']);
        return ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          children: [
            Text(
              '${data['month'] ?? ''} · day ${data['day'] ?? '-'} of ${data['days'] ?? '-'}',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 12),
            Card(
              color: green,
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Estimated bill so far',
                        style: TextStyle(color: mint)),
                    Text(
                      _money(data['bill']),
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 32,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    Text('${_number(data['kwh'])} kWh used',
                        style: const TextStyle(color: Colors.white)),
                    const Divider(color: mint, height: 24),
                    const Text('Projected month-end',
                        style: TextStyle(color: mint)),
                    Text(
                      '${_money(data['proj_bill'])} · ${_number(data['proj_kwh'])} kWh',
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 18,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
            ),
            Row(
              children: [
                Expanded(
                  child: MetricCard(
                    label: 'Potential savings',
                    value: '${_money(data['savings'])}/mo',
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: MetricCard(
                    label: 'Alerts',
                    value: '${alerts.length}',
                    detail: alerts.isEmpty ? 'All normal' : 'Need attention',
                  ),
                ),
              ],
            ),
            SectionTitle('Energy by appliance'),
            if (appliances.isNotEmpty)
              Card(
                child: SizedBox(
                  height: 210,
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Row(
                      children: [
                        Expanded(
                          child: PieChart(
                            PieChartData(
                              centerSpaceRadius: 34,
                              sectionsSpace: 2,
                              sections: appliances.entries
                                  .toList()
                                  .asMap()
                                  .entries
                                  .map((entry) => PieChartSectionData(
                                        value: _double(entry.value.value),
                                        color: colors[entry.key % colors.length],
                                        title: '',
                                        radius: 48,
                                      ))
                                  .toList(),
                            ),
                          ),
                        ),
                        Expanded(
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: appliances.entries
                                .toList()
                                .asMap()
                                .entries
                                .map((entry) => Padding(
                                      padding: const EdgeInsets.symmetric(
                                          vertical: 4),
                                      child: Row(
                                        children: [
                                          CircleAvatar(
                                            radius: 5,
                                            backgroundColor: colors[
                                                entry.key % colors.length],
                                          ),
                                          const SizedBox(width: 8),
                                          Expanded(
                                            child: Text(
                                              '${entry.value.key} · ${_number(entry.value.value)} kWh',
                                              maxLines: 2,
                                              style: Theme.of(context)
                                                  .textTheme
                                                  .labelSmall,
                                            ),
                                          ),
                                        ],
                                      ),
                                    ))
                                .toList(),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            SectionTitle('Last 30 days'),
            Card(
              child: SizedBox(
                height: 230,
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: _trendChart(dates, series),
                ),
              ),
            ),
            SectionTitle('Alerts and next steps'),
            if (alerts.isEmpty)
              const Card(
                child: ListTile(
                  leading: Icon(Icons.check_circle_outline, color: greenMid),
                  title: Text('No unusual consumption detected.'),
                ),
              )
            else
              ...alerts.map((raw) {
                final alert = _map(raw);
                return Card(
                  child: ListTile(
                    isThreeLine: true,
                    leading: const Icon(Icons.warning_amber, color: gold),
                    title: Text(
                        '${alert['appliance'] ?? ''} · ${alert['status'] ?? ''}'),
                    subtitle: Text(
                      '${alert['why'] ?? ''}\nNext: ${alert['rec'] ?? ''} · Potential saving ${_money(alert['rm'])}/mo',
                    ),
                  ),
                );
              }),
          ],
        );
      },
    );
  }
}

class MonthlyPage extends StatefulWidget {
  const MonthlyPage({super.key});

  @override
  State<MonthlyPage> createState() => _MonthlyPageState();
}

class _MonthlyPageState extends State<MonthlyPage> {
  List<String> _months = [];
  String? _month;
  Map<String, dynamic>? _report;
  Object? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadMonths();
  }

  Future<void> _loadMonths() async {
    try {
      final values =
          await context.read<AppState>().api.getList('/api/months');
      _months = values.map((value) => value.toString()).toList();
      _month = _months.isEmpty ? null : _months.first;
      if (_month != null) await _loadReport(_month!);
    } catch (error) {
      _error = error;
      _loading = false;
      if (mounted) setState(() {});
    }
  }

  Future<void> _loadReport(String month) async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      _report = await context
          .read<AppState>()
          .api
          .getMap('/api/monthly', query: {'month': month});
    } catch (error) {
      _error = error;
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null && !_loading) {
      return ErrorPanel(error: _error!, retry: _loadMonths);
    }
    if (_months.isEmpty || _report == null || _loading) {
      return const Center(child: CircularProgressIndicator());
    }
    final report = _report!;
    final series = _map(report['series']);
    final dates = _list(report['dates']);
    final table = _list(report['table']);
    final breakdown = _list(report['breakdown']);
    final heat = _map(report['heat']);
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(16),
      children: [
        DropdownButtonFormField<String>(
          initialValue: _month,
          decoration: const InputDecoration(labelText: 'Report month'),
          items: _months
              .map((month) =>
                  DropdownMenuItem(value: month, child: Text(month)))
              .toList(),
          onChanged: (value) {
            if (value != null) {
              _month = value;
              _loadReport(value);
            }
          },
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            MetricCard(label: 'Total', value: '${_number(report['total'])} kWh'),
            MetricCard(label: 'Bill', value: _money(report['bill'])),
            MetricCard(
                label: 'Daily average', value: '${_number(report['avg'])} kWh'),
            MetricCard(label: 'Peak day', value: '${report['peak_day'] ?? '-'}'),
          ].map((card) => SizedBox(width: 155, child: card)).toList(),
        ),
        SectionTitle('Daily consumption'),
        Card(
          child: SizedBox(
            height: 240,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: _barChart(
                dates.map((_) => 0.0).toList(),
                series: series,
                labels: dates,
              ),
            ),
          ),
        ),
        SectionTitle('Cumulative bill'),
        Card(
          child: SizedBox(
            height: 210,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: _lineChart(_list(report['cum_rm'])),
            ),
          ),
        ),
        SectionTitle('When power is used'),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: _HeatGrid(heat: heat),
          ),
        ),
        SectionTitle('Bill breakdown'),
        Card(
          child: Column(
            children: breakdown.map((row) {
              final item = _map(row);
              return ListTile(
                dense: true,
                title: Text('${item['Charge'] ?? ''}'),
                trailing: Text(_money(item['Amount (RM)'])),
              );
            }).toList(),
          ),
        ),
        SectionTitle('Daily totals'),
        ...table.take(31).map((raw) {
          final row = _map(raw);
          final applianceUse = row.entries
              .where((entry) => entry.key != 'date' && entry.key != 'total')
              .map((entry) => '${entry.key}: ${_number(entry.value)} kWh')
              .join(' · ');
          return Card(
            child: ListTile(
              dense: true,
              title: Text('${row['date'] ?? ''}'),
              subtitle: Text(applianceUse),
              trailing: Text('${_number(row['total'])} kWh'),
            ),
          );
        }),
      ],
    );
  }
}

class _HeatGrid extends StatelessWidget {
  const _HeatGrid({required this.heat});

  final Map<String, dynamic> heat;

  @override
  Widget build(BuildContext context) {
    final hours = _list(heat['y']);
    final values = _list(heat['z']);
    if (hours.isEmpty || values.isEmpty) {
      return const Text('No hourly data for this month.');
    }
    final rowCount = math.min(hours.length, 24).toInt();
    final colCount = _list(values.first).length;
    final maxValue = values
        .expand((row) => _list(row))
        .fold<double>(
          0,
          (maxValue, value) =>
              math.max(maxValue, _double(value)).toDouble(),
        );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Hour by date · darker means more energy'),
        const SizedBox(height: 10),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Column(
            children: List.generate(rowCount, (row) {
              final valuesForHour = _list(values[row]);
              return Row(
                children: [
                  SizedBox(
                    width: 32,
                    child: Text('${hours[row]}',
                        style: Theme.of(context).textTheme.labelSmall),
                  ),
                  ...List.generate(
                    math.min(colCount, valuesForHour.length).toInt(),
                    (column) {
                      final amount = _double(valuesForHour[column]);
                      final opacity =
                          maxValue == 0 ? 0.0 : (amount / maxValue) * .85;
                      return Container(
                        width: 10,
                        height: 9,
                        margin: const EdgeInsets.all(1),
                        decoration: BoxDecoration(
                          color: green.withValues(alpha: opacity),
                          borderRadius: BorderRadius.circular(2),
                        ),
                      );
                    },
                  ),
                ],
              );
            }),
          ),
        ),
      ],
    );
  }
}

class AppliancesPage extends StatefulWidget {
  const AppliancesPage({super.key});

  @override
  State<AppliancesPage> createState() => _AppliancesPageState();
}

class _AppliancesPageState extends State<AppliancesPage> {
  int _reloadKey = 0;

  @override
  Widget build(BuildContext context) {
    final api = context.read<AppState>().api;
    return ApiPage<List<dynamic>>(
      key: ValueKey(_reloadKey),
      load: () async {
        final results = await Future.wait([
          api.getList('/api/appliances'),
          api.getList('/api/actions'),
        ]);
        return [results[0], results[1]];
      },
      builder: (context, raw) {
        final appliances = _list(raw[0]).map(_map).toList();
        final actions = _list(raw[1]).map(_map).toList();
        return ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          children: [
            Text(
              'Appliance usage compared with its normal baseline.',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 8),
            ...appliances.map((appliance) => ApplianceCard(
                  appliance: appliance,
                  onSave: (note) async {
                    await api.post('/api/actions', body: {
                      'appliance': appliance['name'],
                      'note': note,
                    });
                    if (context.mounted) {
                      setState(() => _reloadKey++);
                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('Action saved')),
                      );
                    }
                  },
                )),
            const SectionTitle('Action log and review'),
            if (actions.isEmpty)
              const Card(
                child: ListTile(
                  title: Text('Actions you record appear here.'),
                ),
              )
            else
              ...actions.map((action) => Card(
                    child: ListTile(
                      title: Text(
                          '${action['appliance'] ?? ''} · ${action['note'] ?? ''}'),
                      subtitle: Text(
                        '${action['ts'] ?? ''} · ${action['days_after'] ?? 0} days of readings after action',
                      ),
                      trailing: Text(
                        '${_number(action['before'])} → ${_number(action['after'])}',
                      ),
                    ),
                  )),
          ],
        );
      },
    );
  }
}

class ApplianceCard extends StatefulWidget {
  const ApplianceCard({
    required this.appliance,
    required this.onSave,
    super.key,
  });

  final Map<String, dynamic> appliance;
  final Future<void> Function(String note) onSave;

  @override
  State<ApplianceCard> createState() => _ApplianceCardState();
}

class _ApplianceCardState extends State<ApplianceCard> {
  final _note = TextEditingController();
  bool _saving = false;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final appliance = widget.appliance;
    final status = '${appliance['status'] ?? ''}';
    final chart = _list(appliance['kwh']).map(_double).toList();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '${appliance['name'] ?? ''}',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                Chip(
                  label: Text(status),
                  backgroundColor: status == 'abnormal'
                      ? Colors.red.shade100
                      : status == 'high'
                          ? Colors.amber.shade100
                          : Colors.green.shade100,
                ),
              ],
            ),
            Text('${appliance['room'] ?? ''} · ${appliance['rated_w'] ?? '-'} W'),
            SizedBox(
              height: 130,
              child: _barChart(chart),
            ),
            Wrap(
              spacing: 16,
              runSpacing: 6,
              children: [
                Text('Latest ${_number(appliance['power_w'])} W'),
                Text('${_number(appliance['month_kwh'])} kWh this month'),
                Text('${_number(appliance['recent'])} kWh/day recent'),
              ],
            ),
            const SizedBox(height: 8),
            Text('${appliance['why'] ?? ''}'),
            if (status == 'abnormal' || status == 'high')
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  'Suggested: ${appliance['rec'] ?? ''}\nPossible saving: ${_money(appliance['extra_rm'])}/month',
                  style: const TextStyle(color: green),
                ),
              ),
            const SizedBox(height: 12),
            TextField(
              controller: _note,
              maxLength: 200,
              onChanged: (_) => setState(() {}),
              decoration: const InputDecoration(
                labelText: 'Record an action',
                hintText: 'For example, cleaned the filter',
              ),
            ),
            Align(
              alignment: Alignment.centerRight,
              child: FilledButton.tonalIcon(
                onPressed: _saving || _note.text.trim().isEmpty
                    ? null
                    : () async {
                        setState(() => _saving = true);
                        try {
                          await widget.onSave(_note.text.trim());
                          _note.clear();
                        } catch (error) {
                          if (context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text(error.toString())),
                            );
                          }
                        } finally {
                          if (mounted) setState(() => _saving = false);
                        }
                      },
                icon: const Icon(Icons.save_outlined),
                label: Text(_saving ? 'Saving…' : 'Save action'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class AdvisorPage extends StatefulWidget {
  const AdvisorPage({super.key});

  @override
  State<AdvisorPage> createState() => _AdvisorPageState();
}

class _AdvisorPageState extends State<AdvisorPage> {
  final _controller = TextEditingController();
  final _scroll = ScrollController();
  final List<(bool, String)> _messages = [];
  bool _sending = false;

  static const prompts = [
    'Which appliance should I investigate first?',
    'How can I lower my electricity bill?',
    'What happens if I add an EV charger?',
  ];

  @override
  void dispose() {
    _controller.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _send([String? prompt]) async {
    final question = (prompt ?? _controller.text).trim();
    if (question.isEmpty || _sending) return;
    setState(() {
      _messages.add((true, question));
      _sending = true;
      _controller.clear();
    });
    _scrollToEnd();
    try {
      final response = await context
          .read<AppState>()
          .api
          .post('/api/chat', body: {'question': question});
      if (mounted) {
        setState(() => _messages.add((false, '${response['answer'] ?? ''}')));
      }
    } catch (error) {
      if (mounted) setState(() => _messages.add((false, error.toString())));
    } finally {
      if (mounted) {
        setState(() => _sending = false);
        _scrollToEnd();
      }
    }
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
          child: Wrap(
            spacing: 8,
            children: prompts
                .map((prompt) => ActionChip(
                      label: Text(prompt),
                      onPressed: _sending ? null : () => _send(prompt),
                    ))
                .toList(),
          ),
        ),
        Expanded(
          child: ListView.builder(
            controller: _scroll,
            padding: const EdgeInsets.all(16),
            itemCount: _messages.length + (_sending ? 1 : 0),
            itemBuilder: (context, index) {
              if (_sending && index == _messages.length) {
                return const Align(
                  alignment: Alignment.centerLeft,
                  child: Padding(
                    padding: EdgeInsets.all(12),
                    child: CircularProgressIndicator(),
                  ),
                );
              }
              final (isUser, text) = _messages[index];
              return Align(
                alignment:
                    isUser ? Alignment.centerRight : Alignment.centerLeft,
                child: Container(
                  constraints: const BoxConstraints(maxWidth: 330),
                  margin: const EdgeInsets.symmetric(vertical: 5),
                  padding: const EdgeInsets.all(13),
                  decoration: BoxDecoration(
                    color: isUser ? green : Colors.white,
                    border: isUser
                        ? null
                        : Border.all(color: const Color(0xFFD5E5DC)),
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Text(
                    text,
                    style: TextStyle(color: isUser ? Colors.white : green),
                  ),
                ),
              );
            },
          ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _controller,
                    minLines: 1,
                    maxLines: 4,
                    textInputAction: TextInputAction.send,
                    onSubmitted: (_) => _send(),
                    decoration: const InputDecoration(
                      hintText: 'Ask about your energy use',
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                IconButton.filled(
                  onPressed: _sending ? null : () => _send(),
                  icon: const Icon(Icons.send),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class SimulatorPage extends StatefulWidget {
  const SimulatorPage({super.key});

  @override
  State<SimulatorPage> createState() => _SimulatorPageState();
}

class _SimulatorPageState extends State<SimulatorPage> {
  double _hours = 1;
  double _setpoint = 1;
  double _heater = 20;
  Timer? _debounce;
  Map<String, dynamic>? _result;
  Object? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _calculate();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  void _schedule() {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 250), _calculate);
  }

  Future<void> _calculate() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      _result = await context.read<AppState>().api.getMap(
        '/api/simulate',
        query: {
          'hours': _hours,
          'setpoint': _setpoint.round(),
          'heater': _heater.round(),
        },
      );
    } catch (error) {
      _error = error;
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Widget _slider({
    required String label,
    required double value,
    required double max,
    required int divisions,
    required String display,
    required ValueChanged<double> onChanged,
  }) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(child: Text(label)),
            Text(display, style: const TextStyle(fontWeight: FontWeight.bold)),
          ],
        ),
        Slider(
          value: value,
          min: 0,
          max: max,
          divisions: divisions,
          onChanged: (next) {
            onChanged(next);
            _schedule();
          },
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final result = _result;
    final items = _list(result?['items']).map(_map).toList();
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.all(16),
      children: [
        const Text('Try a few changes and estimate the effect on your bill.'),
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              children: [
                _slider(
                  label: 'Cut AC running hours each day',
                  value: _hours,
                  max: 4,
                  divisions: 8,
                  display: '${_number(_hours)} h',
                  onChanged: (value) => setState(() => _hours = value),
                ),
                _slider(
                  label: 'Raise AC setpoint',
                  value: _setpoint,
                  max: 4,
                  divisions: 4,
                  display: '${_number(_setpoint)} °C',
                  onChanged: (value) => setState(() => _setpoint = value),
                ),
                _slider(
                  label: 'Shorten water-heater use',
                  value: _heater,
                  max: 50,
                  divisions: 10,
                  display: '${_number(_heater)}%',
                  onChanged: (value) => setState(() => _heater = value),
                ),
                const Text(
                  'AC savings assume about 6% less energy per 1°C higher setpoint.',
                  style: TextStyle(color: Colors.black54),
                ),
              ],
            ),
          ),
        ),
        if (_error != null)
          ErrorPanel(error: _error!, retry: _calculate)
        else if (_loading)
          const Padding(
            padding: EdgeInsets.all(24),
            child: Center(child: CircularProgressIndicator()),
          )
        else if (result != null) ...[
          MetricCard(
            label: 'Estimated monthly saving',
            value: _money(result['total_rm']),
            detail: '${_number(result['total_kwh'])} kWh less per month',
          ),
          SectionTitle('Projected bill with changes'),
          Card(
            child: ListTile(
              title: const Text('Current pace'),
              trailing: Text(_money(result['bill_now'])),
            ),
          ),
          Card(
            child: ListTile(
              title: const Text('With changes'),
              trailing: Text(_money(result['bill_after'])),
            ),
          ),
          const SectionTitle('Savings by action'),
          ...items.map((item) => Card(
                child: ListTile(
                  title: Text('${item['action'] ?? ''}'),
                  subtitle: Text('${_number(item['kwh'])} kWh/month'),
                  trailing: Text(_money(item['rm'])),
                ),
              )),
        ],
      ],
    );
  }
}

class SustainabilityPage extends StatelessWidget {
  const SustainabilityPage({super.key});

  @override
  Widget build(BuildContext context) {
    final api = context.read<AppState>().api;
    return ApiPage<Map<String, dynamic>>(
      load: () => api.getMap('/api/sustainability'),
      builder: (context, data) {
        final wins = _list(data['wins']).map(_map).toList();
        final months = _list(data['months']);
        final monthKg = _list(data['month_kg']).map(_double).toList();
        return ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          children: [
            Card(
              color: green,
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Text(
                  'Estimated monthly footprint\n${_number(data['kg'])} kg CO₂',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 24,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ),
            Row(
              children: [
                Expanded(
                  child: MetricCard(
                    label: 'Change vs last month',
                    value: '${_number(_double(data['change']) * 100)}%',
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: MetricCard(
                    label: 'Car distance equivalent',
                    value: '${_number(data['km'])} km',
                  ),
                ),
              ],
            ),
            SectionTitle('Month by month'),
            Card(
              child: SizedBox(
                height: 230,
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: _barChart(monthKg, labels: months),
                ),
              ),
            ),
            const SectionTitle('Ways to reduce your impact'),
            if (wins.isEmpty)
              const Card(
                child: ListTile(
                  title: Text('No unusual energy use detected. Keep it up.'),
                ),
              )
            else
              ...wins.map((win) => Card(
                    child: ListTile(
                      leading: const Icon(Icons.eco_outlined, color: greenMid),
                      title: Text('${win['appliance'] ?? ''}'),
                      subtitle: Text('${win['rec'] ?? ''}'),
                      trailing: Text('${_money(win['rm'])}/mo'),
                    ),
                  )),
            Card(
              child: ExpansionTile(
                title: const Text('How we estimate this'),
                children: [
                  Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text(
                      'CO₂ is estimated from projected electricity use multiplied by ${_number(data['ef'])} kg per kWh. Car and tree equivalents are approximate comparisons.',
                    ),
                  ),
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}

class MetricCard extends StatelessWidget {
  const MetricCard({
    required this.label,
    required this.value,
    this.detail,
    super.key,
  });

  final String label;
  final String value;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: Theme.of(context).textTheme.labelMedium),
            const SizedBox(height: 4),
            Text(
              value,
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    color: green,
                    fontWeight: FontWeight.bold,
                  ),
            ),
            if (detail != null)
              Text(detail!, style: Theme.of(context).textTheme.labelSmall),
          ],
        ),
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.title, {super.key});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 18, bottom: 8),
      child: Text(
        title,
        style: Theme.of(context).textTheme.titleMedium?.copyWith(
              color: green,
              fontWeight: FontWeight.bold,
            ),
      ),
    );
  }
}

Map<String, dynamic> _map(Object? value) =>
    value is Map ? Map<String, dynamic>.from(value) : <String, dynamic>{};

List<dynamic> _list(Object? value) =>
    value is List ? List<dynamic>.from(value) : <dynamic>[];

double _double(Object? value) =>
    value is num ? value.toDouble() : double.tryParse('$value') ?? 0;

String _number(Object? value, {int decimals = 1}) =>
    _double(value).toStringAsFixed(decimals);

String _money(Object? value) => 'RM ${_double(value).toStringAsFixed(2)}';

Widget _trendChart(List<dynamic> dates, Map<String, dynamic> series) {
  final values = <double>[];
  for (final entry in series.values) {
    for (final item in _list(entry)) {
      values.add(_double(item));
    }
  }
  final maxY = values.isEmpty
      ? 1.0
      : values.reduce((a, b) => math.max(a, b).toDouble()) * 1.15;
  final lines = series.entries.toList().asMap().entries.map((entry) {
    final data = _list(entry.value.value);
    return LineChartBarData(
      spots: data
          .asMap()
          .entries
          .map((point) => FlSpot(point.key.toDouble(), _double(point.value)))
          .toList(),
      color: colors[entry.key % colors.length],
      barWidth: 2,
      dotData: const FlDotData(show: false),
    );
  }).toList();
  if (lines.isEmpty) return const Center(child: Text('No trend data'));
  return LineChart(
    LineChartData(
      minY: 0,
      maxY: maxY,
      lineBarsData: lines,
      gridData: const FlGridData(show: true, drawVerticalLine: false),
      titlesData: FlTitlesData(
        topTitles: const AxisTitles(
          sideTitles: SideTitles(showTitles: false),
        ),
        rightTitles: const AxisTitles(
          sideTitles: SideTitles(showTitles: false),
        ),
        bottomTitles: AxisTitles(
          sideTitles: SideTitles(
            showTitles: true,
            interval: math.max(1, dates.length / 4).toDouble(),
            getTitlesWidget: (value, meta) {
              final index = value.toInt();
              if (index < 0 || index >= dates.length) {
                return const SizedBox.shrink();
              }
              final label = '${dates[index]}';
              return Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  label.length >= 10 ? label.substring(5, 10) : label,
                  style: const TextStyle(fontSize: 9),
                ),
              );
            },
          ),
        ),
      ),
    ),
  );
}

Widget _lineChart(List<dynamic> values) {
  final data = values.map(_double).toList();
  if (data.isEmpty) return const Center(child: Text('No report data'));
  final maxY =
      math.max(1.0, data.reduce((a, b) => math.max(a, b).toDouble()) * 1.1)
          .toDouble();
  return LineChart(
    LineChartData(
      minY: 0,
      maxY: maxY,
      gridData: const FlGridData(show: true, drawVerticalLine: false),
      titlesData: const FlTitlesData(
        topTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
        rightTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
        bottomTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
      ),
      lineBarsData: [
        LineChartBarData(
          spots: data
              .asMap()
              .entries
              .map((entry) => FlSpot(entry.key.toDouble(), entry.value))
              .toList(),
          isCurved: true,
          color: green,
          barWidth: 3,
          belowBarData: BarAreaData(
            show: true,
            color: mint.withValues(alpha: .35),
          ),
          dotData: const FlDotData(show: false),
        ),
      ],
    ),
  );
}

Widget _barChart(
  List<double> values, {
  Map<String, dynamic>? series,
  List<dynamic>? labels,
}) {
  final data = values;
  if (series != null) {
    final names = series.keys.toList();
    final count = names.isEmpty ? 0 : _list(series[names.first]).length;
    for (var i = 0; i < count; i++) {
      var total = 0.0;
      for (final name in names) {
        final list = _list(series[name]);
        if (i < list.length) total += _double(list[i]);
      }
      data.add(total);
    }
  }
  if (data.isEmpty) return const Center(child: Text('No report data'));
  final maxY =
      math.max(1.0, data.reduce((a, b) => math.max(a, b).toDouble()) * 1.15)
          .toDouble();
  final interval = math.max(1, (data.length / 6).ceil()).toDouble();
  return BarChart(
    BarChartData(
      maxY: maxY,
      barGroups: data
          .asMap()
          .entries
          .map(
            (entry) => BarChartGroupData(
              x: entry.key,
              barRods: [
                BarChartRodData(
                  toY: entry.value,
                  color: greenMid,
                  width: data.length > 15 ? 7 : 14,
                  borderRadius: BorderRadius.circular(3),
                ),
              ],
            ),
          )
          .toList(),
      gridData: const FlGridData(show: true, drawVerticalLine: false),
      titlesData: FlTitlesData(
        topTitles:
            const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        rightTitles:
            const AxisTitles(sideTitles: SideTitles(showTitles: false)),
        bottomTitles: AxisTitles(
          sideTitles: SideTitles(
            showTitles: labels != null,
            interval: interval.toDouble(),
            getTitlesWidget: (value, meta) {
              if (labels == null) return const SizedBox.shrink();
              final index = value.toInt();
              if (index < 0 || index >= labels.length) {
                return const SizedBox.shrink();
              }
              final label = '${labels[index]}';
              return Padding(
                padding: const EdgeInsets.only(top: 5),
                child: Text(
                  label.length >= 10 ? label.substring(8, 10) : label,
                  style: const TextStyle(fontSize: 9),
                ),
              );
            },
          ),
        ),
      ),
    ),
  );
}
