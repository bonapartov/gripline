import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../services/auth_service.dart';
import '../../services/api_client.dart';
import '../../models/driver_profile.dart';

final pilotProfileProvider = FutureProvider<DriverProfile?>((ref) async {
  final authAsync = ref.watch(authNotifierProvider);
  final user = authAsync.value;
  if (user == null || !user.isPilot) return null;

  final api = ref.watch(apiClientProvider);
  final data = await api.getPilotProfile();
  return DriverProfile.fromJson(data);
});

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authAsync = ref.watch(authNotifierProvider);
    final user = authAsync.value;

    if (user == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Профиль')),
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.lock_outline, size: 48, color: Colors.grey),
              const SizedBox(height: 16),
              const Text('Вы не авторизованы', style: TextStyle(color: Colors.grey)),
              const SizedBox(height: 24),
              ElevatedButton(
                onPressed: () => context.go('/login'),
                child: const Text('Войти'),
              ),
            ],
          ),
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Профиль'),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: () async {
              await ref.read(authNotifierProvider.notifier).logout();
              if (context.mounted) context.go('/login');
            },
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _UserHeader(username: user.username, roles: user.roles),
          const SizedBox(height: 24),
          if (user.isPilot) ...[
            const _SectionHeader('Профиль пилота'),
            const SizedBox(height: 12),
            _PilotProfileCard(),
          ] else ...[
            const _SectionHeader('Ваши роли'),
            const SizedBox(height: 12),
            if (user.roles.isEmpty)
              const _EmptyRoleCard()
            else
              ...user.roles.map((r) => _RoleChip(role: r)),
          ],
        ],
      ),
    );
  }
}

class _UserHeader extends StatelessWidget {
  final String username;
  final List<String> roles;
  const _UserHeader({required this.username, required this.roles});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        CircleAvatar(
          radius: 36,
          backgroundColor: const Color(0xFFE94560).withOpacity(0.2),
          child: Text(
            username.substring(0, 1).toUpperCase(),
            style: const TextStyle(color: Color(0xFFE94560), fontSize: 28, fontWeight: FontWeight.bold),
          ),
        ),
        const SizedBox(width: 16),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(username, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 18)),
              const SizedBox(height: 4),
              Wrap(
                spacing: 6,
                children: roles.isEmpty
                    ? [const _Badge(label: 'болельщик', color: Color(0xFF533483))]
                    : roles.map((r) => _Badge(label: r, color: r == 'pilot' ? const Color(0xFFE94560) : const Color(0xFF0F3460))).toList(),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _Badge extends StatelessWidget {
  final String label;
  final Color color;
  const _Badge({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(
        color: color.withOpacity(0.2),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Text(label, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w600)),
    );
  }
}

class _PilotProfileCard extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final profileAsync = ref.watch(pilotProfileProvider);

    return profileAsync.when(
      loading: () => const Card(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Center(child: CircularProgressIndicator()),
        ),
      ),
      error: (e, _) => Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text('Ошибка: $e', style: const TextStyle(color: Colors.red)),
        ),
      ),
      data: (profile) {
        if (profile == null) {
          return const Card(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: Text('Профиль не найден', style: TextStyle(color: Colors.grey)),
            ),
          );
        }
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(profile.name, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 18)),
                        if (profile.city != null) ...[
                          const SizedBox(height: 4),
                          Row(
                            children: [
                              const Icon(Icons.location_on_outlined, size: 14, color: Colors.grey),
                              const SizedBox(width: 4),
                              Text(profile.city!, style: const TextStyle(color: Colors.grey, fontSize: 13)),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                  if (profile.bestRating != null) ...[
                    Column(
                      children: [
                        Text(
                          (profile.bestRating! * 100).toStringAsFixed(0),
                          style: const TextStyle(color: Color(0xFFE94560), fontWeight: FontWeight.bold, fontSize: 28),
                        ),
                        const Text('рейтинг', style: TextStyle(color: Colors.grey, fontSize: 11)),
                      ],
                    ),
                  ],
                ],
              ),
              if (profile.ratingByClass != null && profile.ratingByClass!.isNotEmpty) ...[
                const Divider(height: 24, color: Colors.white12),
                const Text('Рейтинг по классам', style: TextStyle(color: Colors.grey, fontSize: 12)),
                const SizedBox(height: 8),
                ...profile.ratingByClass!.entries.map((e) => _RatingRow(
                      classId: e.key,
                      data: e.value as Map<String, dynamic>,
                    )),
              ],
            ],
          ),
        );
      },
    );
  }
}

class _RatingRow extends StatelessWidget {
  final String classId;
  final Map<String, dynamic> data;
  const _RatingRow({required this.classId, required this.data});

  @override
  Widget build(BuildContext context) {
    final score = ((data['score'] as num?)?.toDouble() ?? 0.0) * 100;
    final starts = data['starts'] as int? ?? 0;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Text('Класс $classId', style: const TextStyle(color: Colors.white70, fontSize: 13)),
          const Spacer(),
          Text('$starts ст.', style: const TextStyle(color: Colors.grey, fontSize: 12)),
          const SizedBox(width: 12),
          Text(score.toStringAsFixed(1), style: const TextStyle(color: Color(0xFFE94560), fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  final String title;
  const _SectionHeader(this.title);

  @override
  Widget build(BuildContext context) {
    return Text(title, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16));
  }
}

class _EmptyRoleCard extends StatelessWidget {
  const _EmptyRoleCard();

  @override
  Widget build(BuildContext context) {
    return const Card(
      child: Padding(
        padding: EdgeInsets.all(24),
        child: Column(
          children: [
            Icon(Icons.info_outline, color: Colors.grey, size: 32),
            SizedBox(height: 8),
            Text('Ваш аккаунт пока не привязан к пилоту или команде.\nОбратитесь к администратору.', textAlign: TextAlign.center, style: TextStyle(color: Colors.grey, fontSize: 13)),
          ],
        ),
      ),
    );
  }
}

class _RoleChip extends StatelessWidget {
  final String role;
  const _RoleChip({required this.role});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: Icon(
          role == 'pilot' ? Icons.sports_motorsports : Icons.groups,
          color: const Color(0xFFE94560),
        ),
        title: Text(
          role == 'pilot' ? 'Пилот' : 'Менеджер команды',
          style: const TextStyle(color: Colors.white),
        ),
      ),
    );
  }
}
